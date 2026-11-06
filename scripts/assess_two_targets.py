"""Raw detection, held alarm states, event delays and attribution kept separate."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch,HysteresisAlarmDiagnostic,ConditionalResidualDiagnostic
from equipment_diagnostics.evaluation import binary_metrics
from improve_two_targets import hp_enriched
from measured_validation_data import hp_table,hp_batch

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/two_target_improvement'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(n):return json.loads((OUT/n).read_bytes())
def metric(d,key,mask=None):
    y=d.label.to_numpy(bool);a=d[key+'_alarm'].to_numpy(bool);v=d[key+'_valid'].to_numpy(bool)
    e=d.eligible.to_numpy(bool) if 'eligible' in d else np.ones(len(d),bool)
    if mask is not None:e &= np.asarray(mask,bool)
    return binary_metrics(y,a,v,e)

def delays(d,key,module):
    result=[];keys=['file'] if module=='marine' else ['sheet','experiment']
    for name,g in d.groupby(keys,sort=False):
        t=g.time_s.to_numpy();v=g[key+'_valid'].to_numpy(bool);a=g[key+'_alarm'].to_numpy(bool)&v
        e=g.eligible.to_numpy(bool) if 'eligible' in g else np.ones(len(g),bool)
        y=g.label.to_numpy(bool)&e
        starts=np.flatnonzero(y&~np.r_[False,y[:-1]]);ends=np.flatnonzero(y&~np.r_[y[1:],False])
        gap=np.r_[True,np.diff(t)>(5 if module=='marine' else 60)]
        rising=a&(~np.r_[False,a[:-1]]|gap)
        for s,end in zip(starts,ends):
            hit=np.flatnonzero(a[s:end+1]&v[s:end+1]);fresh=np.flatnonzero(rising[s:end+1]&v[s:end+1])
            result.append(dict(identity=list(name) if isinstance(name,tuple) else [name],onset_s=float(t[s]),
                detected=bool(len(hit)),first_active_delay_s=None if not len(hit) else float(t[s+hit[0]]-t[s]),
                already_active_at_onset=bool(s>0 and a[s] and a[s-1] and not gap[s]),
                new_alarm_delay_s=None if not len(fresh) else float(t[s+fresh[0]]-t[s])))
    values=[x['first_active_delay_s'] for x in result if x['detected'] and not x['already_active_at_onset']]
    return dict(events=result,positive_observation_segments=len(result),detected_segments=sum(x['detected'] for x in result),
        already_active_at_onset=sum(x['already_active_at_onset'] for x in result),
        max_delay_s=None if not values else float(max(values)),median_delay_s=None if not values else float(np.median(values)),
        note='Delay starts at provider label/eligible observation, not independently verified physical fault onset. Pre-existing alarms excluded from delay summary.')

def hold(d,key,delay,module):
    a=np.zeros(len(d),bool);v=d[key+'_valid'].to_numpy(bool)
    for name,g in d.groupby('file' if module=='marine' else 'sheet',sort=False):
        episode=np.zeros(len(g),int) if module=='marine' else np.asarray(g.experiment,dtype=str)
        b=SensorBatch(g.time_s.to_numpy(),g[key+'_alarm'].to_numpy(float)[:,None],('raw_alarm',),('1',),
            'recorded_clock','evaluation_asset','reused_measured_evaluation',valid=g[key+'_valid'].to_numpy(bool)[:,None],episodes=episode)
        m=HysteresisAlarmDiagnostic(dict(indication_score='raw_alarm'),on_threshold=.5,confirmation_s=0,
            release_ratio=.5,release_s=delay,max_gap_s=5 if module=='marine' else 60)
        r=m.score(b);assert np.array_equal(r.valid,g[key+'_valid'].to_numpy(bool));a[g.index]=r.alarms
    return v,a

def main():
    r=read('results.json');hp=pd.read_csv(OUT/'heatpump_raw_predictions.csv');marine=pd.read_csv(OUT/'marine_predictions.csv')
    evaluation={};chosen_hp='response_point'
    for name,d in [('marine',marine),('heatpump',hp)]:
        comparisons={}
        for key in r[name]['comparison']:
            entry=dict(metrics=metric(d,key),delay=delays(d,key,name))
            if name=='heatpump':
                entry['EF_metrics']=metric(d,key,d.sheet.str.startswith('EF').to_numpy())
                weak=d.experiment=='EF10.1';entry['EF10_1_metrics']=metric(d,key,weak.to_numpy())
                entry['EF10_1_delay']=delays(d.loc[weak].reset_index(drop=True),key,name)
            comparisons[key]=entry
        evaluation[name]=dict(raw_detection=comparisons,alarm_policy={})
        selected=['baseline','fast_change'] if name=='marine' else ['baseline',chosen_hp]
        for key in selected:
            for delay in (30.,60.):
                policy=key+'_hold'+str(int(delay));valid,alarm=hold(d,key,delay,name)
                d[policy+'_valid']=valid.astype(int);d[policy+'_alarm']=alarm.astype(int)
                entry=dict(metrics=metric(d,policy),delay=delays(d,policy,name),raw_source=key,release_s=delay,
                    meaning='alarm state occupancy only; underlying raw detection unchanged')
                if name=='heatpump':
                    entry['EF_metrics']=metric(d,policy,d.sheet.str.startswith('EF').to_numpy())
                    weak=d.experiment=='EF10.1';entry['EF10_1_metrics']=metric(d,policy,weak.to_numpy());entry['EF10_1_delay']=delays(d.loc[weak].reset_index(drop=True),policy,name)
                evaluation[name]['alarm_policy'][policy]=entry
        d.to_csv(OUT/(name+'_policy_predictions.csv'),index=False)
    # Explanatory ablation and a SENSOR OFFSET test; never call this healthy
    # field false-positive evidence or include it in measured accuracy tables.
    frozen=read('heatpump_frozen.json');c=frozen['models'][chosen_hp]
    model=ConditionalResidualDiagnostic(c['channels'],**c['params']).set_reference(c['reference'])
    d=hp_table('NF10');old=read('heatpump_frozen.json')['splits']['NF10'];b,_,_,_=hp_batch(d,'NF10')
    sel=np.isin(d.index,old['evaluation']);b=b.subset(sel);enriched=hp_enriched('NF10',d.loc[sel],b)
    sensitivity=[]
    for delta in (0.,-.3,.3):
        values=enriched.values.copy();values[:,enriched.channels.index('cond')]+=delta
        perturbed=SensorBatch(enriched.time_s,values,enriched.channels,enriched.units,enriched.clock_id,enriched.asset_id,enriched.origin,
            enriched.valid,enriched.episodes,enriched.modes,enriched.metadata)
        out=model.score(perturbed);sensitivity.append(dict(injected_saturation_temperature_offset_k=delta,
            valid=int(out.valid.sum()),alarms=int(out.alarms.sum()),alarm_fraction=float(out.alarms[out.valid].mean()),
            evidence='synthetic sensor-offset sensitivity on measured normal records, not new physical flow faults or normal field FPR'))
    evaluation['heatpump']['source_specificity']=dict(
        ablation='Compare response_point with without_cond_point: measured-condensing-temperature response supplies the EF10.1 gain.',
        uncertainty='NF10 normal and EF10.1 belong to different sessions/days; available data cannot exclude session/control/sensor bias confounding.',
        measured_weak_saturation_temperature_c=46.5,normal_training_saturation_temperature_c=46.8,
        measurement_accuracy_and_cross_day_repeatability_not_established=True,sensor_offset_sensitivity=sensitivity)
    before=evaluation['heatpump']['raw_detection']['baseline'];after=evaluation['heatpump']['raw_detection'][chosen_hp]
    assert after['metrics']['false_positive_rate_valid']<=before['metrics']['false_positive_rate_valid']
    assert after['EF10_1_metrics']['recall_valid']>before['EF10_1_metrics']['recall_valid']
    assert after['EF10_1_delay']['max_delay_s']<before['EF10_1_delay']['max_delay_s']
    assert all(v['metrics']['false_positive_rate_valid']>evaluation['marine']['raw_detection']['baseline']['metrics']['false_positive_rate_valid']
        for k,v in evaluation['marine']['raw_detection'].items() if k!='baseline')
    decisions=dict(heatpump=dict(development_candidate=chosen_hp,
        scope='measured state-deviation indication on reused cohort; not independent EF fault-specific qualification',
        off_delay_adopted=False,reason='raw branch already improves; hold cannot improve first detection and recovery truth unavailable'),
        marine=dict(selected='baseline',all_new_candidates_rejected=True,reason='Context, multi-lag growth and short-window change candidates all worsen false-positive rate'),
        unchanged_outer_partitions=True,added_normal_files_train_cal_disjoint=True,new_independent_fault_metrics=None)
    (OUT/'assessment.json').write_text(json.dumps(evaluation,indent=2),encoding='utf-8')
    (OUT/'adoption.json').write_text(json.dumps(decisions,indent=2),encoding='utf-8')
    print(json.dumps(dict(hp_weak_before=before['EF10_1_metrics']['recall_valid'],hp_weak_after=after['EF10_1_metrics']['recall_valid'],
        hp_weak_delay_before_s=before['EF10_1_delay']['max_delay_s'],hp_weak_delay_after_s=after['EF10_1_delay']['max_delay_s'],
        marine_default='baseline',sensor_offset_sensitivity=sensitivity),indent=2))
if __name__=='__main__':main()
