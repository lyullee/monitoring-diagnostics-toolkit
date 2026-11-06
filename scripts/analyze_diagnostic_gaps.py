"""Read-only sequential stages1..4 on the frozen v0.11 evaluation artifacts."""
import csv
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd
from equipment_diagnostics import HeatPumpPerformanceDiagnostic
from measured_validation_data import hp_table,hp_batch,HP_CHANNELS,filter_table,ro_table,ro_groups,DATA
from improvement_data import full_filter_trials

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'outputs/filter_heatpump_operating_points';OUT=ROOT/'outputs/diagnostic_gap_analysis'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')
def number(x):return float(x) if np.isfinite(x) else None

def counts(d):
    v=d.eligible.astype(bool)&d.after_valid.astype(bool);y=d.label.astype(bool);a=d.after_alarm.astype(bool)
    tp=int((v&y&a).sum());fn=int((v&y&~a).sum());fp=int((v&~y&a).sum());tn=int((v&~y&~a).sum())
    div=lambda n,z:float(n/z) if z else None
    return dict(total=len(d),eligible=int(d.eligible.sum()),valid=int(v.sum()),TP=tp,FN=fn,FP=fp,TN=tn,
        accuracy=div(tp+tn,tp+fn+fp+tn),recall=div(tp,tp+fn),false_positive_rate=div(fp,fp+tn),coverage=div(int(v.sum()),int(d.eligible.sum())))

def segment_runs(flag,t,breaks):
    runs=[];start=None
    for i in range(len(flag)):
        if breaks[i] and start is not None:runs.append((start,i-1));start=None
        if flag[i] and start is None:start=i
        if not flag[i] and start is not None:runs.append((start,i-1));start=None
    if start is not None:runs.append((start,len(flag)-1))
    return runs

def event_summary(d,group):
    events=[];windows=[];exposure=0.;negative_exposure=0.;negative_fragments=0
    for key,g in d.groupby(group,sort=True):
        g=g.reset_index(drop=True);t=g.time_s.to_numpy(float);v=g.eligible.to_numpy(bool)&g.after_valid.to_numpy(bool)
        y=g.label.to_numpy(bool);a=g.after_alarm.to_numpy(bool)&v
        dt=float(np.median(np.diff(t))) if len(t)>1 else 0.;breaks=np.r_[True,np.diff(t)>max(60,3*dt)]
        breaks|=np.r_[False,~v[:-1]]
        # Sample-cell exposure: nominal dt per eligible valid observation. Gaps
        # never become observed exposure. No24h extrapolation of short trials.
        exposure+=float(v.sum()*dt);negative_exposure+=float((v&~y).sum()*dt)
        negative_fragments+=len(segment_runs(a&~y,t,breaks))
        for lo,hi in segment_runs(a,t,breaks):
            events.append(dict(group=str(key),start_s=float(t[lo]),duration_s=float(t[hi]-t[lo]+dt),
                positive_overlap=bool(y[lo:hi+1].any()),negative_overlap=bool((~y[lo:hi+1]).any())))
        for lo,hi in segment_runs(y&v,t,breaks):
            ix=np.flatnonzero(a[lo:hi+1]);delay=float(t[lo+ix[0]]-t[lo]) if len(ix) else None
            windows.append(dict(group=str(key),start_s=float(t[lo]),observed_duration_s=float(t[hi]-t[lo]+dt),
                detected=bool(len(ix)),delay_from_first_eligible_positive_s=delay,alarm_already_active_at_window_start=bool(a[lo])))
            windows[-1]['left_censored_positive_window']=bool(lo==0 or y[lo-1] or not v[lo-1])
    fp=[e for e in events if not e['positive_overlap']];delays=[w['delay_from_first_eligible_positive_s'] for w in windows if w['detected']]
    return dict(valid_observed_hours=exposure/3600,negative_observed_hours=negative_exposure/3600,
        alarm_segments=len(events),pure_negative_alarm_segments=len(fp),alarm_segments_with_negative_overlap=sum(e['negative_overlap'] for e in events),
        negative_alarm_fragments=negative_fragments,
        positive_windows=len(windows),detected_positive_windows=sum(w['detected'] for w in windows),
        delay_median_s=float(np.median(delays)) if delays else None,delay_max_s=max(delays) if delays else None,
        alarm_duration_median_s=float(np.median([e['duration_s'] for e in events])) if events else None,
        alarm_duration_max_s=max([e['duration_s'] for e in events],default=None),
        segments=events,windows=windows,
        limitation='Observed label windows after exclusions, not verified physical fault onsets. Continuous alarms are segments, not independent causes. No daily rate extrapolation.')

def inputs():
    hp=pd.read_csv(BASE/'heatpump_reused_predictions.csv');lookup={}
    for sheet in hp.sheet.unique():
        d=hp_table(sheet)
        for i,row in d.iterrows():lookup[(sheet,int(i))]=(str(row['Test code']),float(row['Fault intensity']))
    hp['experiment']=[lookup[(s,int(i))][0] for s,i in zip(hp.sheet,hp.source_row)]
    hp['intensity']=[lookup[(s,int(i))][1] for s,i in zip(hp.sheet,hp.source_row)]
    test=pd.read_csv(BASE/'reused_original_test_predictions.csv');raw=filter_table('test')
    for col in ['Dust','Dust_feed','Flow_rate','Differential_pressure']:
        test[col]=raw.loc[test.source_row,col].to_numpy()
    suffix=pd.read_csv(BASE/'reused_uncensored_suffix_predictions.csv');full,_=full_filter_trials();meta=filter_table('train').groupby('Data_No').first();fl={int(g.Data_No.iloc[0]):g for g in full}
    for col in ['Dust','Dust_feed']:suffix[col]=[meta.loc[int(i),col] for i in suffix.trial]
    for col in ['Flow_rate','Differential_pressure']:suffix[col]=[fl[int(i)].loc[int(j),col] for i,j in zip(suffix.trial,suffix.source_row)]
    return hp,test,suffix

def stage1(hp,test,suffix):
    return dict(heatpump=event_summary(hp,['sheet','experiment']),filter_original_test=event_summary(test,['trial']),
        filter_reused_suffix=event_summary(suffix,['trial']))

def stage2(hp):
    frozen=json.loads((BASE/'heatpump_frozen.json').read_text());m=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**frozen['parameters'],persistence_s=30).set_reference(frozen['reference'])
    results=[]
    for sheet in ['EF10','EF12']:
        d=hp_table(sheet);b,e,y,codes=hp_batch(d,sheet);r=m.score(b)
        stored=hp[hp.sheet==sheet].set_index('source_row')
        assert np.array_equal(stored.loc[d.index,'after_alarm'].to_numpy(bool),r.alarms)
        for code in sorted(set(codes)):
            mask=e&(codes==code);ix=np.flatnonzero(mask);miss=mask&~r.alarms
            if not len(ix):continue
            positive=(r.scores[mask]>1)
            results.append(dict(sheet=sheet,experiment=code,intensity=float(d.loc[mask,'Fault intensity'].iloc[0]),
                metrics=counts(stored.loc[d.index[mask]].reset_index()),
                indications_above_threshold=int(positive.sum()),pending_or_intermittent=int((miss&(r.scores>1)).sum()),
                below_threshold_missed=int((miss&(r.scores<=1)).sum()),
                raw_metric_medians={k:number(np.nanmedian(r.metrics[k][mask])) for k in ['heating_cop','electric_power_w','evaporating_temperature_k','log_compressor_speed']},
                score_quantiles=[number(x) for x in np.nanquantile(r.scores[mask],[.1,.5,.9])]))
    return dict(by_experiment=results,label_used_only_for_evaluation=True,signal_resolution_note='No new sensor accuracy claim; low-intensity state overlap and sampled precision constrain separation.')

def stage3(test,suffix):
    result={}
    ff=json.loads((BASE/'filter_frozen.json').read_text());raw=filter_table('train');tr=raw[raw.Data_No.isin(ff['training_ids'])]
    for title,d in [('original_test',test),('reused_suffix',suffix)]:
        groups={}
        for column in ['Dust','Dust_feed']:
            groups[column]={str(k):counts(g) for k,g in d.groupby(column)}
        d=d.copy();d['rul_band']=pd.cut(d.rul_s,[-.001,10,20,30,40,60,np.inf],right=True).astype(str)
        groups['rul_band']={str(k):counts(g) for k,g in d.groupby('rul_band')}
        groups['trial']={str(k):counts(g) for k,g in d.groupby('trial')}
        groups['observed_flow_outside_training_csv_range']=dict(training_min=float(tr.Flow_rate.min()),training_max=float(tr.Flow_rate.max()),
            eligible_outside_rows=int(((d.eligible==1)&((d.Flow_rate<tr.Flow_rate.min())|(d.Flow_rate>tr.Flow_rate.max()))).sum()))
        result[title]=groups
    return result

def stage4():
    files=[]
    for name,archive in [('steady_state/steady_state.csv','steady_state.zip'),*ro_groups()]:
        d=ro_table(name,archive);pf=d['Feed Pressure (psi)'].to_numpy(float);pc=d['Reject Pressure (psi)'].to_numpy(float);diff=pf-pc
        finite=np.isfinite(diff);order=finite&(diff>=0)
        files.append(dict(file=name,rows=len(d),finite_pressure_rows=int(finite.sum()),feed_ge_reject_rows=int(order.sum()),
            feed_minus_reject_psi_quantiles=[number(x) for x in np.quantile(diff[finite],[0,.01,.5,.99,1])],
            median_absolute_difference_psi=number(np.median(abs(diff[finite])))))
    raw=(DATA/'ro_nrel/README.rtf').read_text(encoding='utf-8',errors='replace')
    # Retain relevant original text as evidence; do not silently repair sensors.
    snippets=[raw[max(0,m.start()-80):m.end()+180] for m in re.finditer(r'(?i)pressure|calibrat|sensor|gauge|absolute',raw)]
    return dict(files=files,readme_sha256=sha(DATA/'ro_nrel/README.rtf'),original_pressure_context=snippets,
        conclusion='README does not establish a pressure offset correction or prove swapped columns. Strict reference remains blocked; no swap, clipping or fitted offset applied.',
        acquisition_url='https://mhkdr.openei.org/submissions/649',fault_truth_available=False,
        next_requirement='Sensor locations, pressure reference and independent calibration information from provider or another labeled dataset.')

def main():
    OUT.mkdir(parents=True,exist_ok=True);before={n:sha(BASE/n) for n in ['results.json','protocol.json','filter_frozen.json','heatpump_frozen.json']}
    hp,test,suffix=inputs()
    for n,fn in [('1_events',lambda:stage1(hp,test,suffix)),('2_heatpump_misses',lambda:stage2(hp)),('3_filter_conditions',lambda:stage3(test,suffix)),('4_ro_quality',stage4)]:
        save(n+'.json',fn());print(n,'completed',flush=True)
    assert before=={n:sha(BASE/n) for n in before}
    save('analysis_protocol.json',dict(baseline_files_sha256=before,sequence=[1,2,3,4],references_unchanged=True,
        all_data_reused=True,source_sha256={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))}))
if __name__=='__main__':main()
