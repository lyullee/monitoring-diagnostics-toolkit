import numpy as np
import pytest
from equipment_diagnostics.evaluation import binary_metrics


def test_abstention_is_not_a_correct_negative_or_a_detected_fault():
    b=lambda x:np.array(x,bool)
    m=binary_metrics(b([0,0,0,1,1,1]),b([0,1,1,1,0,1]),b([1,1,0,1,1,0]))
    assert [m[k] for k in ('TN','FP','TP','FN','unknown')]==[1,1,1,1,2]
    assert m['accuracy_valid']==.5 and m['false_positive_rate_valid']==.5
    assert m['fault_detection_all_eligible']==pytest.approx(1/3)
    assert m['accuracy_unknown_as_incorrect']==pytest.approx(1/3)


def test_empty_class_denominators_are_unavailable():
    m=binary_metrics(np.array([False]),np.array([False]),np.array([False]))
    assert m['false_positive_rate_valid'] is None and m['accuracy_valid'] is None
    assert m['coverage']==0 and m['balanced_accuracy_valid'] is None
    with pytest.raises(ValueError): binary_metrics([0],[False],[True])
