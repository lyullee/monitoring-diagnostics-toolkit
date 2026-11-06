"""Binary screening metrics that keep abstentions out of true negatives."""
import numpy as np


def binary_metrics(labels, alarms, valid, eligible=None):
    arrays = [np.asarray(x) for x in (labels, alarms, valid)]
    if not arrays or arrays[0].ndim != 1 or any(a.shape != arrays[0].shape or a.dtype.kind != 'b' for a in arrays):
        raise ValueError('labels, alarms and valid must be aligned boolean vectors')
    y,a,v = arrays
    e = np.ones(y.shape,bool) if eligible is None else np.asarray(eligible)
    if e.shape != y.shape or e.dtype.kind != 'b':
        raise ValueError('eligible must be an aligned boolean vector')
    v = v & e
    a = a & v
    tp=int(np.sum(v & y & a)); fn=int(np.sum(v & y & ~a))
    fp=int(np.sum(v & ~y & a)); tn=int(np.sum(v & ~y & ~a))
    ratio=lambda n,d: float(n/d) if d else None
    sensitivity=ratio(tp,tp+fn); specificity=ratio(tn,tn+fp)
    return {'total':len(y),'eligible':int(e.sum()),'excluded':int((~e).sum()),
        'valid':int(v.sum()),'unknown':int(np.sum(e & ~v)),
        'normal_eligible':int(np.sum(e & ~y)),'fault_eligible':int(np.sum(e & y)),
        'normal_unknown':int(np.sum(e & ~y & ~v)),'fault_unknown':int(np.sum(e & y & ~v)),
        'TP':tp,'FN':fn,'FP':fp,'TN':tn,'coverage':ratio(int(v.sum()),int(e.sum())),
        'coverage_all_rows':ratio(int(v.sum()),len(y)),
        'eligible_fraction_all_rows':ratio(int(e.sum()),len(y)),
        'normal_coverage':ratio(tn+fp,int(np.sum(e & ~y))),
        'fault_coverage':ratio(tp+fn,int(np.sum(e & y))),
        'accuracy_valid':ratio(tp+tn,int(v.sum())),
        'balanced_accuracy_valid':None if sensitivity is None or specificity is None else (sensitivity+specificity)/2,
        'recall_valid':sensitivity,'false_positive_rate_valid':ratio(fp,fp+tn),
        'precision_valid':ratio(tp,tp+fp),
        'fault_detection_all_eligible':ratio(tp,int(np.sum(e & y))),
        'accuracy_unknown_as_incorrect':ratio(tp+tn,int(e.sum()))}
