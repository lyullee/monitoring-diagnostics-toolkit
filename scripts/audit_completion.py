"""Independent source/label/metric replay, raw operating-pressure arithmetic and split audit."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def count(label,alarm,valid,eligible=None):
    label=np.asarray(label,bool);alarm=np.asarray(alarm,bool);valid=np.asarray(valid,bool)
    if eligible is None:eligible=np.ones(len(label),bool)
    v=valid&eligible
    tp=int((v&label&alarm).sum());fn=int((v&label&~alarm).sum());fp=int((v&~label&alarm).sum());tn=int((v&~label&~alarm).sum())
    div=lambda a,b:None if b==0 else a/b
    return dict(TP=tp,FN=fn,FP=fp,TN=tn,valid=int(v.sum()),eligible=int(eligible.sum()),unknown=int((eligible&~valid).sum()),
        accuracy_valid=div(tp+tn,tp+tn+fp+fn),recall_valid=div(tp,tp+fn),false_positive_rate_valid=div(fp,fp+tn),coverage=div(v.sum(),eligible.sum()))
def compare(a,b):
    for k,v in a.items():
        if v is None:assert b[k] is None,k
        else:assert abs(v-b[k])<1e-11,(k,v,b[k])
def persist(t,score,valid,seconds,max_gap,episodes=None):
    out=np.zeros(len(t),bool);start=None
    for i in range(len(t)):
        if i==0 or not valid[i] or not valid[i-1] or t[i]-t[i-1]>max_gap or (episodes is not None and episodes[i]!=episodes[i-1]):start=None
        if not valid[i] or score[i]<=1:start=None
        else:
            if start is None:start=t[i]
            out[i]=t[i]-start>=seconds
    return out
def replay_pressure(frame,model):
    p=frame['Shaft Power'].to_numpy()*1000;s=frame['Engine Speed'].to_numpy()/60;dp=frame['Compressor Filter Loss'].to_numpy()
    ref=model['reference'];params=model['params'];valid=np.isfinite(p)&np.isfinite(s)&np.isfinite(dp)&(p>0)&(s>0)&(dp>0)
    for key,x in [('shaft_power_w',p),('engine_speed_hz',s)]:
        lo,hi=ref['envelope'][key];valid &= (x>=lo)&(x<=hi)
    if params['conditioned']:
        m=ref['pressure_model'];x=(np.column_stack((np.log(p),np.log(s)))-m['center'])/m['scale']
        a,b=x.T;design=np.column_stack((np.ones(len(a)),a,b,a*a,a*b,b*b))
        expected=np.exp(design@np.asarray(m['coefficients']))
    else:expected=np.full(len(p),ref['center'])
    raw=np.maximum(dp-expected,0)/np.maximum(params['minimum_excess_pa'],params['growth_limit_fraction']*expected)
    return raw/ref['score_calibration']['threshold'],valid,raw

def main():
    checks={};results={}
    for name in ('chiller','wet_coil','independent_marine'):
        path=OUT/name/'results.json';r=json.loads(path.read_bytes());f=OUT/name/'frozen.json'
        assert r['frozen_sha256']==sha(f)
        if name=='chiller':
            for filename,digest in json.loads(f.read_bytes())['source_sha256'].items():
                assert sha(ROOT/filename)==digest,filename
        pred=pd.read_csv(OUT/name/'predictions.csv');key='source' if name=='chiller' else 'run' if name=='wet_coil' else 'file'
        if name=='chiller':assert np.array_equal(pred.label.to_numpy(bool),~pred.source.str.contains('/Benchmark Tests/').to_numpy())
        if name=='wet_coil':assert np.array_equal(pred.label.to_numpy(bool),pred.run.str.startswith('F').to_numpy())
        for policy,expected in r['comparison'].items():
            compare(count(pred.label,pred[policy+'_alarm'],pred[policy+'_valid'],pred.eligible.to_numpy(bool) if 'eligible' in pred else None),expected)
        results[name]=dict(results_sha256=sha(path),prediction_sha256=sha(OUT/name/'predictions.csv'),recounted_rows=len(pred))
    # Replay independent marine source labels, arithmetic and actual persistence.
    folder=OUT/'independent_marine';frozen=json.loads((folder/'frozen.json').read_bytes())
    raw=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip'
    assert sha(raw)==frozen['raw_sha256'];z=zipfile.ZipFile(raw)
    refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'));ref=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2])
    split={k:np.asarray(ix) for k,ix in frozen['split_indices'].items()}
    for a,b in [('train','calibration'),('train','normal_evaluation'),('calibration','normal_evaluation')]:
        assert not set(split[a])&set(split[b])
        x=ref.Time.to_numpy()[split[a]];y=ref.Time.to_numpy()[split[b]];j=np.searchsorted(x,y)
        distance=np.minimum(abs(x[np.clip(j,0,len(x)-1)]-y),abs(x[np.clip(j-1,0,len(x)-1)]-y))
        assert distance.min()>20
    assert not set(frozen['test_files'])&{refname}
    pred=pd.read_csv(folder/'predictions.csv');replayed=0
    for name,g in pred.groupby('file',sort=False):
        if name==refname:
            ix=split['normal_evaluation'];frame=ref.iloc[ix];label=np.zeros(len(ix),bool);t=frame.Time.to_numpy();ep=np.cumsum(np.r_[True,np.diff(ix)>1])
        else:
            frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);label=frame['Anomaly State'].to_numpy(bool);t=frame.Time_rel.to_numpy();ep=None
        assert np.array_equal(g.label.to_numpy(bool),label);np.testing.assert_array_equal(g.time_s,t)
        for policy,model in frozen['models'].items():
            score,valid,_=replay_pressure(frame,model)
            assert np.array_equal(valid,g[policy+'_valid'].to_numpy(bool))
            np.testing.assert_allclose(score[valid],g[policy+'_score'].to_numpy()[valid],rtol=1e-11,atol=1e-12)
            alarm=persist(t,score,valid,10,5,ep)
            assert np.array_equal(alarm,g[policy+'_alarm'].to_numpy(bool))
        replayed+=len(frame)
    for policy,model in frozen['models'].items():
        cal=ref.iloc[split['calibration']];_,valid,raw_score=replay_pressure(cal,model)
        threshold=max(1.,float(np.nextafter(np.quantile(raw_score[valid],.99),np.inf)))
        assert abs(threshold-model['reference']['score_calibration']['threshold'])<1e-11
    checks['marine_source_labels_scores_persistence_replayed_rows']=replayed
    checks['marine_global_partition_purge_s']=20
    # Simulation labels are declared scenarios, never presented as measured truth.
    p=OUT/'physics/results.json';r=json.loads(p.read_bytes());assert r['frozen_sha256']==sha(OUT/'physics/frozen.json')
    pred=pd.read_csv(OUT/'physics/predictions.csv')
    for policy,g in pred[pred.module=='vaporizer'].groupby('policy'):
        compare(count(g.label,g.alarm,g.valid),r['vaporizer'][policy])
    g=pred[pred.module=='boiler'];compare(count(g.label,g.alarm,g.valid,g.time_s.to_numpy()>=60),r['boiler']['metrics'])
    results['physics']=dict(results_sha256=sha(p),evidence_type='simulation_only',recounted_rows=len(pred))
    for item in json.loads((ROOT/'research_support/public_data/completion_20261106/download_manifest.json').read_bytes()):
        p=ROOT/item['file'];assert sha(p)==item['sha256'] and 'md5:'+hashlib.md5(p.read_bytes()).hexdigest()==item['publisher_md5']
    checks['three_downloaded_corpora_publisher_checksums_verified']=True
    audit=dict(successful=True,checks=checks,evaluations=results,
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))},
        scope='Independent label/count/pressure arithmetic/persistence/split/checksum replay. Does not certify field representativeness or producer fault labels.')
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(dict(successful=True,checks=checks),indent=2))
if __name__=='__main__':main()
