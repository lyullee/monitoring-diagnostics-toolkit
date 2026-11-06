"""Independent arithmetic/state/count replay for new raw and alarm-hold paths."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch
from improve_two_targets import hp_enriched
from measured_validation_data import hp_table,hp_batch
from validate_independent_marine import make as legacy_marine

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/two_target_improvement'
def read(n):return json.loads((OUT/n).read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def counts(y,a,v,e):
    y=np.asarray(y,bool);a=np.asarray(a,bool);v=np.asarray(v,bool)&np.asarray(e,bool)
    tp=int((v&y&a).sum());fn=int((v&y&~a).sum());fp=int((v&~y&a).sum());tn=int((v&~y&~a).sum())
    div=lambda n,d:None if d==0 else n/d
    return dict(TP=tp,FN=fn,FP=fp,TN=tn,valid=int(v.sum()),eligible=int(np.sum(e)),
        accuracy_valid=div(tp+tn,v.sum()),recall_valid=div(tp,tp+fn),false_positive_rate_valid=div(fp,fp+tn),coverage=div(v.sum(),np.sum(e)))
def compare(a,b):
    for k,v in a.items():
        if v is None:assert b[k] is None,k
        else:assert abs(v-b[k])<1e-10,(k,v,b[k])
def reset(b,v,gap):
    r=np.ones(len(v),bool)
    r[1:]=~v[1:]|~v[:-1]|(np.diff(b.time_s)>gap)|(b.episodes[1:]!=b.episodes[:-1])
    if b.modes is not None:r[1:] |= b.modes[1:]!=b.modes[:-1]
    return r
def alarms(b,score,valid,persistence,gap):
    breaks=reset(b,valid,gap);out=np.zeros(len(valid),bool);start=None
    for i,t in enumerate(b.time_s):
        if breaks[i]:start=None
        if not valid[i] or score[i]<=1:start=None
        else:
            if start is None:start=t
            out[i]=t-start>=persistence
    return out
def conditional(b,c):
    p=c['params'];ref=c['reference'];m=ref['conditional_model'];fo=p['feature_order'];to=p['target_order']
    assert m['feature_order']==fo and m['target_order']==to
    arrays={};valid=np.ones(len(b.time_s),bool)
    for role,s in {**p['features'],**p['targets']}.items():
        value,ok=b.column(c['channels'][role],s['unit']);valid &= ok
        if s['log'] or s['unit'] in ('K','W','1/s'):valid &= value>0
        with np.errstate(all='ignore'):arrays[role]=np.log(value) if s['log'] else value
        valid &= np.isfinite(arrays[role])
    x=np.column_stack([arrays[k] for k in fo]);y=np.column_stack([arrays[k] for k in to]);scaled=(x-m['center'])/m['scale']
    columns=[np.ones(len(x)),*scaled.T]
    if p['degree']==2:columns.extend(scaled[:,i]*scaled[:,j] for i in range(len(fo)) for j in range(i,len(fo)))
    expected=np.column_stack(columns)@np.asarray(m['coefficients'])+m['residual_center'];z=(y-expected)/m['residual_scale']
    for i,k in enumerate(ref['envelope']):
        lo,hi=ref['envelope'][k];valid &= (x[:,i]>=lo)&(x[:,i]<=hi)
    valid &= np.isfinite(z).all(axis=1);breaks=reset(b,valid,p['max_gap_s']);accepted=valid.copy();mean=z.copy();start=0
    if p['window_s']:
        for i,t in enumerate(b.time_s):
            if not valid[i]:start=i+1;continue
            if breaks[i]:start=i
            j=max(start,int(np.searchsorted(b.time_s,t-p['window_s'])))
            mean[i]=z[j:i+1].mean(axis=0)
            accepted[i]=t-b.time_s[start]>=p['window_s']
    scores=[]
    for i,k in enumerate(to):
        direction=p['targets'][k]['direction'];scores.append(abs(mean[:,i]) if direction==0 else np.maximum(direction*mean[:,i],0))
    raw=np.max(np.column_stack(scores),axis=1);cal=ref['residual_calibration'];cut=np.full(len(raw),cal['threshold'])
    if p.get('calibration_role'):
        cut[:]=np.nan;context=x[:,fo.index(p['calibration_role'])]
        for g in cal['groups']:cut[context==g['context']]=g['threshold']
    score=raw/cut;accepted &= np.isfinite(score)
    return score,accepted,alarms(b,score,accepted,p['persistence_s'],p['max_gap_s'])
def growth(b,c,old):
    p=c['params'];ref=c['reference'];m=old['reference']['pressure_model']
    power=b.values[:,0];speed=b.values[:,1];dp=b.values[:,4]
    x=(np.column_stack((np.log(power),np.log(speed)))-m['center'])/m['scale'];a,d=x.T
    expected=np.exp(np.column_stack((np.ones(len(x)),a,d,a*a,a*d,d*d))@m['coefficients']);signal=np.log(dp/expected)
    v=np.isfinite(signal)&(dp>0)&(power>0)&(speed>0)
    for key,a in [('shaft_power_w',power),('engine_speed_hz',speed)]:
        lo,hi=old['reference']['envelope'][key];v &= (a>=lo)&(a<=hi)
    br=reset(b,v,p['max_gap_s']);mean=np.zeros(len(v));available=np.zeros(len(v),bool);start=0
    for i,t in enumerate(b.time_s):
        if not v[i]:start=i+1;continue
        if br[i]:start=i
        j=max(start,int(np.searchsorted(b.time_s,t-p['mean_window_s'])))
        mean[i]=np.mean(signal[j:i+1]);available[i]=t-b.time_s[start]>=p['mean_window_s']
    score=np.zeros(len(v));accepted=np.zeros(len(v),bool);start=0
    for i,t in enumerate(b.time_s):
        if not v[i]:start=i+1;continue
        if br[i]:start=i
        values=[]
        for lag,cut in zip(p['lags_s'],ref['change_scales']):
            j=int(np.searchsorted(b.time_s,t-lag,side='right'))-1
            if j>=start and available[i] and available[j] and t-lag-b.time_s[j]<=p['max_gap_s']:
                values.append(max(0,mean[i]-mean[j])/cut)
        if values:score[i]=max(values)/ref['change_calibration']['threshold'];accepted[i]=True
    return score,accepted,alarms(b,score,accepted,p['persistence_s'],p['max_gap_s'])
def check_path(g,key,result):
    score,v,a=result
    assert np.array_equal(v,g[key+'_path_valid'].to_numpy(bool)),key
    np.testing.assert_allclose(score[v],g[key+'_path_score'].to_numpy()[v],rtol=1e-8,atol=1e-9)
    assert np.array_equal(a,g[key+'_path_alarm'].to_numpy(bool)),key

def main():
    r=read('results.json');assessment=read('assessment.json');replayed=0
    for n,h in r['source_sha256'].items():assert sha(ROOT/n)==h,n
    for name in ['marine','heatpump']:assert sha(OUT/(name+'_frozen.json'))==r[name]['frozen_sha256']
    # Additional normal source rows have no overlap with legacy AF evaluation.
    manifest=read('marine_added_normal_manifest.json');old=json.loads((ROOT/'outputs/completion_7_13/independent_marine/frozen.json').read_bytes())
    f=read('marine_frozen.json');assert f['outer_split']==old['split_indices']
    z=zipfile.ZipFile(ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip')
    trainfiles=set();calfiles=set()
    for name,item in manifest['files'].items():
        assert name not in old['test_files'];assert hashlib.sha256(z.read(name)).hexdigest()==item['member_sha256']
        frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);ix=item['source_rows'];assert (frame.iloc[ix]['Anomaly State']==0).all()
        (trainfiles if item['split']=='train' else calfiles).add(name)
    assert not trainfiles&calfiles
    # Whole-file separation alone is insufficient if a publisher reused rows.
    # Check common measured/derived vectors, excluding clocks and gold labels.
    refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    reference=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2]);columns=sorted(set(reference.columns)-{'Time'})
    def row_hashes(frame):return set(pd.util.hash_pandas_object(frame[columns].astype(float).round(8),index=False).tolist())
    protected=row_hashes(reference.iloc[old['split_indices']['normal_evaluation']])
    for filename in old['test_files']:protected |= row_hashes(pd.read_csv(io.BytesIO(z.read(filename)),skiprows=[1,2]))
    added={'train':set(),'calibration':set()}
    for filename,item in manifest['files'].items():
        frame=pd.read_csv(io.BytesIO(z.read(filename)),skiprows=[1,2]).iloc[item['source_rows']]
        hashes=row_hashes(frame);assert not hashes&protected
        added[item['split']] |= hashes
    assert not added['train']&added['calibration']
    assert not added['train']&row_hashes(reference.iloc[old['split_indices']['calibration']])
    assert not added['calibration']&row_hashes(reference.iloc[old['split_indices']['train']])
    for file in ['marine_normal_cv.json','heatpump_normal_cv.json']:
        cv=read(file);entries=[cv] if 'chosen' in cv else cv.values()
        for entry in entries:
            expected=min(entry['candidates'],key=lambda x:(x['mean_scaled_mse'],x['degree'],len(x['features'])))
            assert expected==entry['chosen']
            assert all(d['minimum_temporal_separation_s']>20 for candidate in entry['candidates'] for d in candidate['folds'])
    # Source-label/time and independent matrix/window replay, including JSON reload order.
    predictions=pd.read_csv(OUT/'marine_predictions.csv');refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    for name,g in predictions.groupby('file',sort=False):
        frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);ep=None
        if name==refname:
            ix=np.asarray(old['split_indices']['normal_evaluation']);frame=frame.iloc[ix];ep=np.cumsum(np.r_[True,np.diff(ix)>1]);y=np.zeros(len(frame),bool)
        else:y=frame['Anomaly State'].to_numpy(bool)
        b0=legacy_marine(frame,name,name==refname,ep)
        b=SensorBatch(b0.time_s,np.column_stack((frame['Shaft Power']*1000,frame['Engine Speed']/60,frame['Engine room Temp.']+273.15,
            frame['Charge Air IC Cooling Water Temp. In']+273.15,frame['Compressor Filter Loss'])),
            ('power','speed','ambient','cooling','dp'),('W','1/s','K','K','Pa'),b0.clock_id,b0.asset_id,b0.origin,episodes=b0.episodes)
        assert np.array_equal(g.label.to_numpy(bool),y);np.testing.assert_array_equal(g.time_s,b.time_s)
        for key,c in f['models'].items():
            dynamic=c['kind']=='window_residual_change'
            result=growth(b,c,old['models']['load_conditioned_pressure']) if dynamic else conditional(b,c)
            check_path(g,key,result);_,v,a=result;oldv=g.baseline_valid.to_numpy(bool);olda=g.baseline_alarm.to_numpy(bool)
            combined=olda|(v&a&oldv) if dynamic else np.where(v,a,olda)
            assert np.array_equal(combined,g[key+'_alarm'].to_numpy(bool));replayed+=len(v)
    f=read('heatpump_frozen.json');assert f['splits']==json.loads((ROOT/'outputs/literature_improvement/heatpump_frozen.json').read_bytes())['splits']
    hp=pd.read_csv(OUT/'heatpump_raw_predictions.csv')
    for sheet,g in hp.groupby('sheet',sort=False):
        d=hp_table(sheet);b,e,y,codes=hp_batch(d,sheet)
        if sheet.startswith('NF'):
            ix=np.isin(d.index,f['splits'][sheet]['evaluation']);b=b.subset(ix);e=e[ix];y=y[ix];d=d.loc[ix]
        assert np.array_equal(g.label.to_numpy(bool),y) and np.array_equal(g.source_row,d.index)
        np.testing.assert_array_equal(g.time_s,b.time_s)
        bs={'main':hp_enriched(sheet,d,b),'aux':hp_enriched(sheet,d,b,True)}
        for key,c in f['models'].items():
            signal=bs['aux' if key.startswith('aux_') else 'main'];result=conditional(signal,c);check_path(g,key,result)
            _,v,a=result;combined=g.baseline_alarm.to_numpy(bool)|(a&v&g.baseline_valid.to_numpy(bool))
            assert np.array_equal(combined,g[key+'_alarm'].to_numpy(bool));replayed+=len(v)
    # Count all raw / held states independently; replay off delays without the policy class.
    for module in ['marine','heatpump']:
        data=pd.read_csv(OUT/(module+'_policy_predictions.csv'));e=data.eligible.to_numpy(bool) if module=='heatpump' else np.ones(len(data),bool)
        for section in ['raw_detection','alarm_policy']:
            for key,item in assessment[module][section].items():
                compare(counts(data.label,data[key+'_alarm'],data[key+'_valid'],e),item['metrics'])
                if module=='heatpump':
                    compare(counts(data.label,data[key+'_alarm'],data[key+'_valid'],e&(data.experiment=='EF10.1').to_numpy()),item['EF10_1_metrics'])
                if section=='alarm_policy':
                    source=item['raw_source'];delay=item['release_s'];computed=np.zeros(len(data),bool)
                    for _,g in data.groupby('file' if module=='marine' else 'sheet',sort=False):
                        active=False;off=None;t=g.time_s.to_numpy();v=g[source+'_valid'].to_numpy(bool);raw=g[source+'_alarm'].to_numpy(bool)
                        ep=np.zeros(len(g),int) if module=='marine' else g.experiment.to_numpy()
                        for j,index in enumerate(g.index):
                            if j==0 or not v[j] or not v[j-1] or t[j]-t[j-1]>(5 if module=='marine' else 60) or ep[j]!=ep[j-1]:active=False;off=None
                            if not v[j]:continue
                            if raw[j]:active=True;off=None
                            elif active:
                                if off is None:off=t[j]
                                if t[j]-off>=delay:active=False;off=None
                            computed[index]=active
                    assert np.array_equal(computed,data[key+'_alarm'].to_numpy(bool)),key
    audit=dict(successful=True,results_sha256=sha(OUT/'results.json'),assessment_sha256=sha(OUT/'assessment.json'),
        adoption_sha256=sha(OUT/'adoption.json'),source_sha256=r['source_sha256'],independent_prediction_replayed_rows=replayed,
        outer_splits_unchanged=True,added_normal_files_disjoint=True,normal_only_cv_selection_verified=True,
        shared_sensor_vectors_with_protected_evaluation=0,added_train_cal_shared_sensor_vectors=0,
        sorted_json_model_order_verified=True,raw_and_held_states_independently_recounted=True,
        scope='Same actual evaluations reused. Additional normal data same engine. Auxiliary extraction uses reviewed loader; all model arithmetic and held states independently replayed. No new independent fault qualification.')
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(dict(successful=True,replayed_rows=replayed),indent=2))
if __name__=='__main__':main()
