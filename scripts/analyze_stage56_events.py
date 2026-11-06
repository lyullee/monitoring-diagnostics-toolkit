"""Event comparisons for adopted heat-pump profile and experimental filter."""
import json
from pathlib import Path
import pandas as pd
from analyze_diagnostic_gaps import event_summary,counts

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/stage56_ensemble'
def main():
    events={};strata={}
    for name,file,keys in [('heatpump','heatpump_predictions.csv',['sheet','experiment']),('filter_original_test','filter_original_test_predictions.csv',['trial']),('filter_reused_suffix','filter_reused_suffix_predictions.csv',['trial'])]:
        d=pd.read_csv(OUT/file);before=d.copy();before['after_valid']=before.before_valid;before['after_alarm']=before.before_alarm
        events[name]=dict(before=event_summary(before,keys),after_candidate=event_summary(d,keys))
        group='experiment' if name=='heatpump' else 'material'
        strata[name]={str(k):{'before':counts(before.loc[g.index]),'after_candidate':counts(g)} for k,g in d.groupby(group)}
    (OUT/'event_comparison.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
    (OUT/'stratified_comparison.json').write_text(json.dumps(strata,indent=2),encoding='utf-8')
    print('Event and condition comparisons generated')
if __name__=='__main__':main()
