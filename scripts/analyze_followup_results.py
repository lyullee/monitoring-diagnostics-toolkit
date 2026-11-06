"""Apply the same event/stratification definitions to the final before/after CSVs."""
import json
from pathlib import Path
import pandas as pd
from analyze_diagnostic_gaps import event_summary,counts
from improve_filter_heatpump import digest

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/diagnostic_followup'

def main():
    events={};detail={}
    for name,file,keys in [('heatpump','heatpump_predictions.csv',['sheet','experiment']),('filter_original_test','filter_original_test_predictions.csv',['trial']),('filter_reused_suffix','filter_reused_suffix_predictions.csv',['trial'])]:
        d=pd.read_csv(OUT/file);before=d.copy();before['after_valid']=before.before_valid;before['after_alarm']=before.before_alarm
        events[name]={'before':event_summary(before,keys),'after':event_summary(d,keys)}
        if name=='heatpump':detail[name]={'by_experiment':{str(k):{'before':counts(before.loc[g.index]),'after':counts(g)} for k,g in d.groupby(['sheet','experiment'])}}
        else:
            v=d.eligible.astype(bool)&d.after_valid.astype(bool);warning=v&(d.training_support_fraction<1)
            detail[name]={'by_material':{str(k):{'before':counts(before.loc[g.index]),'after':counts(g)} for k,g in d.groupby('material')},
                'support_warning_rows':int(warning.sum()),'support_warning_fraction':float(warning.sum()/v.sum()),
                'support_warning_metrics':counts(d.loc[warning]),'support_inside_metrics':counts(d.loc[v&~warning]),
                'tree_vote_std_quantiles':d.loc[v,'tree_vote_std'].quantile([.1,.5,.9]).to_list(),
                'uncertainty_interpretation':'Descriptive ensemble dispersion and feature support, not calibrated fault probability or confidence interval; decisions not suppressed.'}
    (OUT/'event_comparison.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
    (OUT/'stratified_comparison.json').write_text(json.dumps(detail,indent=2),encoding='utf-8')
    print(json.dumps({k:{p:{n:e[n] for n in ['alarm_segments','negative_alarm_fragments','positive_windows','detected_positive_windows','delay_median_s','delay_max_s']} for p,e in v.items()} for k,v in events.items()},indent=2))
if __name__=='__main__':main()
