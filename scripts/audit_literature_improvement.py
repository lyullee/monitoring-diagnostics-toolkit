"""Independently replay signed/AR1 CUSUM against source rows and frozen references."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import HeatPumpPerformanceDiagnostic,LoadConditionedPressureDiagnostic
from measured_validation_data import hp_table,hp_batch,HP_CHANNELS
from validate_independent_marine import make as marine_batch

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/literature_improvement'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def counts(y,a,v,e=None):
    y=np.asarray(y,bool);a=np.asarray(a,bool);v=np.asarray(v,bool)
    e=np.ones(len(y),bool) if e is None else np.asarray(e,bool);v=v&e
    tp=int((v&y&a).sum());fn=int((v&y&~a).sum());fp=int((v&~y&a).sum());tn=int((v&~y&~a).sum())
    div=lambda a,b:None if b==0 else a/b
    return dict(TP=tp,FN=fn,FP=fp,TN=tn,eligible=int(e.sum()),valid=int(v.sum()),unknown=int((e&~v).sum()),
        accuracy_valid=div(tp+tn,v.sum()),recall_valid=div(tp,tp+fn),false_positive_rate_valid=div(fp,fp+tn),coverage=div(v.sum(),e.sum()))
def compare(actual,want):
    for k,v in actual.items():
        if v is None:assert want[k] is None,k
        else:assert abs(v-want[k])<1e-11,(k,v,want[k])

def replay(b,x,contexts,input_valid,config):
    p=config['params'];ref=config['reference'];groups={g['context']:g for g in ref['signed_groups']}
    n=len(x);z=np.full(n,np.nan);limits=z.copy();valid=input_valid.copy()&np.isfinite(x)&np.isfinite(contexts)
    for i in range(n):
        group=groups.get(contexts[i])
        if group is None:valid[i]=False;continue
        z[i]=(x[i]-group['center'])/group['scale'];limits[i]=group['limit']
    # Reset is determined before AR1 first-observation abstention.
    reset=np.ones(n,bool)
    for i in range(1,n):reset[i]=(not valid[i] or not valid[i-1] or b.time_s[i]-b.time_s[i-1]>p.get('max_gap_s',60)
        or b.episodes[i]!=b.episodes[i-1] or contexts[i]!=contexts[i-1]
        or (b.modes is not None and b.modes[i]!=b.modes[i-1]))
    raw_z=z.copy()
    if p['prewhiten']:
        for i in range(n):
            if not valid[i] or reset[i]:valid[i]=False;z[i]=np.nan;continue
            g=groups[contexts[i]];z[i]=(raw_z[i]-g['ar1_phi']*raw_z[i-1]-g['innovation_center'])/g['innovation_scale']
    stat=np.full(n,np.nan);total=0.
    for i in range(n):
        if not valid[i]:total=0.;continue
        if reset[i]:total=0.
        dt=p['reference_step_s'] if reset[i] else b.time_s[i]-b.time_s[i-1]
        total=max(0.,total+(z[i]-p['drift_sigma'])*dt/p['reference_step_s']);stat[i]=total
    score=stat/limits;valid &= np.isfinite(score);alarm=np.zeros(n,bool);since=None
    # persistence_s is explicitly stored alongside params by this audit's caller.
    for i in range(n):
        broken=(i==0 or not valid[i-1] or not valid[i] or b.episodes[i]!=b.episodes[i-1]
            or b.time_s[i]-b.time_s[i-1]>p['max_gap_s'])
        if broken:since=None
        if not valid[i] or score[i]<=1:since=None
        else:
            if since is None:since=b.time_s[i]
            alarm[i]=b.time_s[i]-since>=p['persistence_s']
    return score,valid,alarm

def config_with_policy(c,gap,persistence):
    return dict(params={**c['params'],'max_gap_s':gap,'persistence_s':persistence},reference=c['reference'])

def event_report(d,policies,module):
    rows=[];keys=['file'] if module=='marine' else ['sheet','experiment']
    for ident,g in d.groupby(keys,sort=False):
        t=g.time_s.to_numpy();e=np.ones(len(g),bool) if module=='marine' else g.eligible.to_numpy(bool)
        y=g.label.to_numpy(bool)&e
        for policy in policies:
            v=g[policy+'_valid'].to_numpy(bool)&e;a=g[policy+'_alarm'].to_numpy(bool)&v
            gap=np.r_[True,np.diff(t)>(5 if module=='marine' else 60)]
            rising=a&(~np.r_[False,a[:-1]]|gap)
            pos=y&v;starts=np.flatnonzero(pos&~np.r_[False,pos[:-1]]);ends=np.flatnonzero(pos&~np.r_[pos[1:],False])
            events=[]
            for s,end in zip(starts,ends):
                hit=np.flatnonzero(a[s:end+1]);fresh=np.flatnonzero(rising[s:end+1])
                events.append(dict(onset_s=float(t[s]),detected=bool(len(hit)),delay_s=None if not len(hit) else float(t[s+hit[0]]-t[s]),
                    alarm_already_active_at_observed_onset=bool(s>0 and a[s] and a[s-1] and not gap[s]),
                    new_alarm_after_observed_onset=bool(len(fresh)),new_alarm_delay_s=None if not len(fresh) else float(t[s+fresh[0]]-t[s])))
            neg=a&~y
            normal=v&~y
            exposure=float(np.sum(np.diff(t)[normal[1:]&normal[:-1]&~gap[1:]]))
            false_fragments=int((neg&(~np.r_[False,neg[:-1]]|gap)).sum())
            rows.append(dict(identity=list(ident) if isinstance(ident,tuple) else [ident],policy=policy,
                positive_observation_segments=events,false_positive_fragments=false_fragments,
                observed_normal_exposure_s=exposure,false_positive_fragments_per_observed_normal_hour=None if exposure<=0 else false_fragments/(exposure/3600)))
    return rows

def main():
    result=read(OUT/'results.json');protocol=read(OUT/'protocol.json')
    for name,h in result['source_sha256'].items():assert sha(ROOT/name)==h,name
    assert sha(OUT/'literature.json')==protocol['literature_sha256']
    replayed=0;drift=[]
    # Frozen same-source marine residuals and original publisher labels.
    cfg=read(OUT/'marine_frozen.json');base_dir=ROOT/'outputs/completion_7_13/independent_marine'
    assert sha(OUT/'marine_frozen.json')==result['marine']['frozen_sha256']
    old=read(base_dir/'frozen.json');up=old['models']['load_conditioned_pressure']
    model=LoadConditionedPressureDiagnostic(dict(pressure_drop='dp',shaft_power='power',engine_speed='speed'),**up['params'],max_gap_s=5,persistence_s=10).set_reference(up['reference'])
    source=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip';assert sha(source)==old['raw_sha256']
    z=zipfile.ZipFile(source);refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    ref=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2]);d=pd.read_csv(OUT/'marine_predictions.csv')
    for name,g in d.groupby('file',sort=False):
        if name==refname:
            ix=np.asarray(old['split_indices']['normal_evaluation']);frame=ref.iloc[ix];b=marine_batch(frame,name,True,np.cumsum(np.r_[True,np.diff(ix)>1]));label=np.zeros(len(ix),bool)
        else:frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);b=marine_batch(frame,name);label=frame['Anomaly State'].to_numpy(bool)
        assert np.array_equal(label,g.label.to_numpy(bool));np.testing.assert_array_equal(b.time_s,g.time_s)
        p=up['reference']['pressure_model'];features=(np.column_stack((np.log(frame['Shaft Power']*1000),np.log(frame['Engine Speed']/60)))-p['center'])/p['scale']
        a,c=features.T;design=np.column_stack((np.ones(len(a)),a,c,a*a,a*c,c*c))
        expected=np.exp(design@p['coefficients']);signal=np.log(frame['Compressor Filter Loss'].to_numpy()/expected)
        valid=model.score(b).valid
        normal=~label&valid;drift.append(dict(module='marine',file=name,normal_rows=int(normal.sum()),
            normal_log_residual_mean=float(np.mean(signal[normal])),normal_log_residual_std=float(np.std(signal[normal]))))
        for key,candidate in cfg['variants'].items():
            score,v,alarm=replay(b,signal,np.ones(len(b.time_s)),valid,config_with_policy(candidate,5,10))
            np.testing.assert_allclose(score[v],g[key+'_score'].to_numpy()[v],rtol=1e-9,atol=1e-10)
            assert np.array_equal(v,g[key+'_valid'].to_numpy(bool));assert np.array_equal(alarm,g[key+'_alarm'].to_numpy(bool))
            replayed+=len(v)
    for key,m in result['marine']['comparison'].items():compare(counts(d.label,d[key+'_alarm'],d[key+'_valid']),m)
    marine_events=event_report(d,result['marine']['comparison'],'marine')
    # Heatpump projection rebuilt from raw measurements and frozen regression.
    f=read(OUT/'heatpump_frozen.json');assert sha(OUT/'heatpump_frozen.json')==result['heatpump']['frozen_sha256']
    upstream=read(ROOT/'outputs/filter_heatpump_operating_points/heatpump_frozen.json')
    model=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**upstream['parameters'],persistence_s=30).set_reference(upstream['reference'])
    m=upstream['reference']['refrigerant_model'];d=pd.read_csv(OUT/'heatpump_predictions.csv')
    prior=pd.read_csv(ROOT/'outputs/stage56_ensemble/heatpump_predictions.csv')
    for sheet,g in d.groupby('sheet',sort=False):
        frame=hp_table(sheet);b,e,label,codes=hp_batch(frame,sheet)
        if sheet.startswith('NF'):
            ix=np.isin(frame.index,f['splits'][sheet]['evaluation']);b=b.subset(ix);e=e[ix];label=label[ix];frame=frame.loc[ix]
        assert np.array_equal(g.source_row,frame.index) and np.array_equal(g.label.to_numpy(bool),label)
        np.testing.assert_array_equal(g.time_s,b.time_s)
        q,p,te=b.values[:,0],b.values[:,1],b.values[:,2];demand=b.values[:,-1]
        design=np.column_stack((np.ones(len(q)),(demand-m['load_center'])/m['load_scale']))
        pred=design@np.asarray(m['coefficients'])+m['residual_center']
        indices=[m['targets'].index(k) for k in ('evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop')]
        signed=(np.column_stack((te,np.log(p),np.log(b.values[:,7]),np.log(q/p)))-pred[:,indices])/np.asarray(m['residual_scale'])[indices]*[-1,1,1,-1]
        signal=np.full(len(q),np.nan)
        for group in f['projection_groups']:
            ix=demand==group['context'];signal[ix]=(signed[ix]-group['center'])@group['weights']
        oldg=prior[prior.sheet==sheet];assert np.array_equal(oldg.after_alarm,g.baseline_alarm)
        valid=model.score(b).valid
        for key,candidate in f['variants'].items():
            x=signal.copy();v=valid.copy()
            if key.startswith('source_proxy_'):
                with np.errstate(all='ignore'):x=-np.log((q-p)/(283.15-te))
                v=b.valid.all(axis=1)&(q>p)&(p>0)&(te>0)&(te<283.15)&np.isfinite(x)
            score,cv,alarm=replay(b,x,demand,v,config_with_policy(candidate,60,0))
            recorded=g[key+'_score'].to_numpy();assert np.array_equal(cv,np.isfinite(recorded))
            np.testing.assert_allclose(score[cv],recorded[cv],rtol=1e-9,atol=1e-10)
            fused=g.baseline_alarm.to_numpy(bool)|(alarm&cv&g.baseline_valid.to_numpy(bool))
            assert np.array_equal(fused,g[key+'_alarm'].to_numpy(bool));replayed+=len(cv)
    for key,m in result['heatpump']['comparison'].items():compare(counts(d.label,d[key+'_alarm'],d[key+'_valid'],d.eligible.to_numpy(bool)),m)
    weak=d[(d.experiment=='EF10.1')&(d.eligible==1)]
    weakmetrics={k:counts(weak.label,weak[k+'_alarm'],weak[k+'_valid']) for k in result['heatpump']['comparison']}
    heatpump_events=event_report(d,result['heatpump']['comparison'],'heatpump')
    def qualifies(after,before):
        return after['recall_valid']>=before['recall_valid'] and after['false_positive_rate_valid']<=before['false_positive_rate_valid'] and after['coverage']>=before['coverage']
    hp_ok={k:qualifies(m,result['heatpump']['comparison']['baseline']) for k,m in result['heatpump']['comparison'].items() if k!='baseline'}
    marine_ok={k:qualifies(m,result['marine']['comparison']['baseline']) for k,m in result['marine']['comparison'].items() if k!='baseline'}
    decision=dict(heatpump=dict(selected_development_candidate='signed_block60',candidate_qualifies=hp_ok,
        rationale='Both signed variants pass reused-cohort metrics; choose blocked limit as a development decision motivated by serial dependence. Not independent model-selection validation.',
        weak_EF10_1_improved=False),marine=dict(candidate_qualifies=marine_ok,selected='baseline',
        retained_reference='outputs/completion_7_13/independent_marine/frozen.json',reason='Every cumulative candidate increases measured false positives substantially.'),
        new_independent_fault_qualification=False)
    assert hp_ok['signed_block60'] and not any(marine_ok.values())
    (OUT/'adoption.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    events=dict(marine=marine_events,heatpump=heatpump_events,heatpump_weak_metrics=weakmetrics,
        notes='HP positive observation segments start after frozen180s eligibility; these are not independently timed physical fault events.')
    (OUT/'events_and_strata.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
    (OUT/'normal_shift_analysis.json').write_text(json.dumps(drift,indent=2),encoding='utf-8')
    audit=dict(successful=True,results_sha256=sha(OUT/'results.json'),source_sha256=result['source_sha256'],
        independent_signed_ar1_cusum_replayed_rows=replayed,original_labels_and_time_verified=True,
        baseline_decisions_reproduced=True,decision_sha256=sha(OUT/'adoption.json'),weak_EF10_1_metrics=weakmetrics,
        scope='Independent new score/state/fusion/count reconstruction from raw/frozen inputs; upstream validity uses previously verified diagnostic. No new blind or field qualification.')
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(dict(successful=True,replayed_rows=replayed),indent=2))
if __name__=='__main__':main()
