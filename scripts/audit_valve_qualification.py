"""Independent stdlib-only recount of new background and historical-positive replay."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'qualification'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def count(c,y,a,v,e):
    c['total']+=1;c['eligible' if e else 'excluded']+=1
    if not e:return
    c['fault_eligible' if y else 'normal_eligible']+=1
    if not v:c['unknown']+=1;return
    c['valid']+=1;c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
def check(c,m):
    for k in ('total','eligible','excluded','unknown','valid','TP','FN','FP','TN'):assert c[k]==m[k],(k,c[k],m[k])
    for k,n,d in [('coverage',c['valid'],c['eligible']),('accuracy_valid',c['TP']+c['TN'],c['valid']),
                  ('recall_valid',c['TP'],c['TP']+c['FN']),('false_positive_rate_valid',c['FP'],c['FP']+c['TN'])]:
        assert m[k]==(n/d if d else None),k
def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    p=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    assert digest(OUT/'frozen_protocol.json')==r['protocol_sha256']
    for name,h in r['source_sha256'].items():assert digest(ROOT/name)==h,name
    for name,h in p['data_sha256'].items():assert digest(ROOT/name)==h,name
    assert len(set(p['new_background_dates']+p['historical_positive_replay_dates']+[p['train_date'],p['calibration_date']]))==25
    assert r['new_independent_positive_tests']==0
    totals={};groups={};episodes=Counter();seconds=Counter();previous={};seen=set();event_state={};events={}
    with (OUT/'predictions.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            cohort=row['cohort'];asset=row['asset'];date=row['date'];t=float(row['time_s'])
            seen.add((cohort,asset,date));y=row['label']=='1';e=row['eligible']=='1';v=row['valid']=='1'
            for policy in ('baseline','sustained'):
                a=row[policy+'_alarm']=='1';assert not a or v
                key=(cohort,policy);filekey=(cohort,asset,date,policy)
                count(totals.setdefault(key,Counter()),y,a,v,e)
                count(groups.setdefault(filekey,Counter()),y,a,v,e)
                normal_alarm=e and v and not y and a
                if normal_alarm and not previous.get(filekey,False):episodes[filekey]+=1
                previous[filekey]=normal_alarm
                if e and v and not y:seconds[filekey]+=1
                evkey=(asset,date,policy)
                if y:
                    if evkey not in event_state:event_state[evkey]={'start':t,'end':t,'hit':None}
                    state=event_state[evkey];state['end']=t
                    if e and v and a and state['hit'] is None:state['hit']=t
                elif evkey in event_state:
                    state=event_state.pop(evkey);events[(*evkey,state['start'])]=state
    assert not event_state
    expected={(c,a,d) for c,dates in [('new_background',p['new_background_dates']),('historical_replay',p['historical_positive_replay_dates'])]
        for a in ('A1','A3') for d in dates}
    assert seen==expected
    for (cohort,policy),c in totals.items():check(c,r['comparison'][cohort][policy])
    for item in r['files']:
        for policy,data in item['policies'].items():
            key=(item['cohort'],item['asset'],item['date'],policy)
            check(groups[key],data['metrics']);assert episodes[key]==data['normal_alarm_episodes']
            assert seconds[key]==data['normal_valid_seconds']
    for event in r['events']:
        actual=events[event['asset'],event['date'],event['policy'],event['start']]
        assert actual['end']==event['end'] and event['detected']==(actual['hit'] is not None)
        assert event['delay_s']==(actual['hit']-actual['start'] if actual['hit'] is not None else None)
    assert len(events)==len(r['events'])==12
    gates=p['gates'];recomputed={}
    for policy in ('baseline','sustained'):
        m=r['comparison']['new_background'][policy];h=r['comparison']['historical_replay'][policy]
        files=[v['policies'][policy] for v in r['files'] if v['cohort']=='new_background']
        ep=sum(episodes[k] for k in groups if k[0]=='new_background' and k[-1]==policy)
        sec=sum(seconds[k] for k in groups if k[0]=='new_background' and k[-1]==policy);rate=ep/(sec/86400)
        ev=[e for e in r['events'] if e['policy']==policy]
        checks={'new_background_fpr':m['false_positive_rate_valid']<=gates['new_background_fpr_max'],
            'new_background_coverage':m['coverage']>=gates['new_background_coverage_min'],
            'worst_asset_day_fpr':max(v['metrics']['false_positive_rate_valid'] for v in files)<=gates['worst_asset_day_fpr_max'],
            'alarm_episode_rate':rate<=gates['alarm_episode_rate_per_24h_max'],
            'worst_asset_day_episodes':max(v['normal_alarm_episodes'] for v in files)<=gates['worst_asset_day_alarm_episodes_max'],
            'historical_event_recall':sum(e['detected'] for e in ev)/len(ev)>=gates['historical_fault_event_recall_min'],
            'historical_sample_recall':h['recall_valid']>=gates['historical_fault_sample_recall_min'],
            'historical_detection_delay':all(e['detected'] and e['delay_s']<=gates['historical_detection_delay_max_s'] for e in ev)}
        d=r['decisions'][policy];assert checks==d['checks'] and all(checks.values())==d['passes_project_monitoring_gates']
        assert ep==d['new_background_alarm_episodes'] and abs(rate-d['normal_alarm_episodes_per_24h'])<1e-12
        recomputed[policy]=checks
    report={'successful':True,'independently_recounted_metrics_episodes_events_and_gates':True,
        'new_date_file_disjointness_verified':True,'source_data_and_protocol_hashes_verified':True,
        'independent_positive_tests':0,'gate_results':recomputed,'results_sha256':digest(OUT/'results.json'),
        'predictions_sha256':digest(OUT/'predictions.csv')}
    (OUT/'independent_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
