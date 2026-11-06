"""Pinned MATLAB reader for HSE v8, independently checked against original CSV."""
import io
import zipfile
import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.io.matlab import _mio5
from measured_validation_data import DATA,filter_table


def full_filter_trials():
    with zipfile.ZipFile(DATA/'filter_hse'/'filter.zip') as z:
        raw=loadmat(io.BytesIO(z.read('Train_Data_Uncensored.mat')))['__function_workspace__'].tobytes()
    # MATLAB v5 MCOS table workspace: SciPy's public loadmat drops anonymous
    # variables, so read the first anonymous matrix explicitly. Reject any layout
    # differing from the pinned publisher artifact; this is not a general parser.
    stream=io.BytesIO(raw);reader=_mio5.MatFile5Reader(stream)
    reader.byte_order='<';reader.initialize_read();stream.seek(8)
    header,_=reader.read_var_header();a=reader.read_var_array(header,process=False)
    meta=a['MCOS'][0,0]['_ObjectMetadata'][0].ravel()
    assert len(meta)==362
    original=filter_table('train');frames=[];checks=[]
    for i in range(50):
        cols=meta[2+7*i].ravel()
        names=[str(s.ravel()[0]) for s in meta[7+7*i].ravel()]
        assert names==['Differential_presure','Flow_rate','Time']
        assert len(cols)==3
        v=np.column_stack([c.ravel() for c in cols]);assert np.isfinite(v).all()
        d=pd.DataFrame(v,columns=['Differential_pressure','Flow_rate','Time'])
        d['Data_No']=i+1;g=original[original.Data_No==i+1]
        assert len(d)>=len(g)
        err=float(abs(v[:len(g)]-g[['Differential_pressure','Flow_rate','Time']].to_numpy()).max())
        assert err<1e-9
        if not np.all(np.diff(d.Time)>0):
            checks.append(dict(trial=i+1,full_rows=len(d),old_prefix_rows=len(g),prefix_max_abs_error=err,
                excluded_reason='nonmonotonic original uncensored clock; no invented continuation'))
            continue
        crossed=np.flatnonzero(d.Differential_pressure.to_numpy()>600)
        assert len(crossed) and crossed[0]==len(d)-1
        d['RUL']=float(d.Time.iloc[crossed[0]])-d.Time
        d['new_observation']=np.arange(len(d))>=len(g)
        checks.append(dict(trial=i+1,full_rows=len(d),old_prefix_rows=len(g),prefix_max_abs_error=err))
        frames.append(d)
    return frames,checks
