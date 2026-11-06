"""Adapters for the acquired observations; labels are returned outside SensorBatch."""
from pathlib import Path
import io
import zipfile
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch
from equipment_diagnostics.observed_inputs import relative_flow,filmtec_inverse_temperature_factor,ideal_nacl_osmotic_pressure

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'research_support'/'public_data'/'acquisition_20261105'
HP_CHANNELS=dict(condenser_duty='q',electric_power='p',evaporating_temperature='te',condensing_temperature='tc',
    liquid_line_temperature='tl',discharge_temperature='td',refrigerant_mass_flow='mass',compressor_speed='speed',heat_demand='demand')

def concatenate(batches):
    a=batches[0];order=np.argsort(np.concatenate([b.time_s for b in batches]),kind='stable')
    return SensorBatch(np.concatenate([b.time_s for b in batches])[order],np.concatenate([b.values for b in batches])[order],
        a.channels,a.units,a.clock_id,a.asset_id,a.origin,np.concatenate([b.valid for b in batches])[order],
        np.concatenate([b.episodes for b in batches])[order],metadata=a.metadata)

def filter_table(split):
    with zipfile.ZipFile(DATA/'filter_hse'/'filter.zip') as z:
        return pd.read_csv(io.BytesIO(z.read('Train_Data_CSV.csv' if split=='train' else 'Test_Data_CSV.csv')))

def filter_batch(d,flow_reference,*,episode='filter'):
    return SensorBatch(d.Time.to_numpy(float),np.column_stack((d.Differential_pressure,relative_flow(d.Flow_rate,flow_reference))),
        ('dp','flow_ratio'),('Pa','1'),'hse_seconds','hse_CC600G_population','laboratory_measured',
        episodes=np.full(len(d),episode),metadata={'flow_basis':'raw flow / training-only raw reference; absolute unit not assumed',
            'reference_population':'multiple distinct filter specimens, manufacturing variability retained'})

def ro_table(member,archive):
    with zipfile.ZipFile(DATA/'ro_nrel'/archive) as z:return pd.read_csv(io.BytesIO(z.read(member)))

def ro_groups():
    groups=[]
    for archive in ('ramp.zip','sine.zip'):
        with zipfile.ZipFile(DATA/'ro_nrel'/archive) as z:
            groups.extend((n,archive) for n in z.namelist() if n.endswith('.csv') and not n.startswith('__MACOSX/'))
    return sorted(groups)

def ro_batch(d,*,corrected,episode,pressure_basis='strict_mean'):
    t_c=d['Feed Temperature (C)'].to_numpy(float);t=t_c+273.15
    pf=d['Feed Pressure (psi)'].to_numpy(float)*6894.757293168
    pc=d['Reject Pressure (psi)'].to_numpy(float)*6894.757293168
    # Documented sensor-conductivity relation; g/L equals kg/m3 numerically.
    cf=d['Feed Conductivity (mS/cm)'].to_numpy(float)*.6638
    cc=d['Reject Conductivity (mS/cm)'].to_numpy(float)*.6638
    cp=d['Permeate 1 Conductivity (uS/cm)'].to_numpy(float)*.001*.6638
    if pressure_basis not in ('strict_mean','feed_only_assumption'):raise ValueError('invalid RO pressure basis')
    ndp=(.5*pf+.5*pc if pressure_basis=='strict_mean' else pf) # permeate gauge pressure assumed zero
    factor=np.ones(len(d))
    if corrected:
        ndp=ndp-(.5*ideal_nacl_osmotic_pressure(cf,t)+.5*ideal_nacl_osmotic_pressure(cc,t)-ideal_nacl_osmotic_pressure(cp,t))
        factor=filmtec_inverse_temperature_factor(t_c)
    q=d['Permeate 1 Flowrate (L/min)'].to_numpy(float)*.001/60
    stamp=d['Runtime (min)'].to_numpy(float)*60
    # Source groups can restart clocks; preserve each clock run as an episode and
    # use a monotonic acquisition index (documented 0.25s) rather than sorting rows.
    changes=np.r_[True,np.diff(stamp)<=0]
    for col in ('Steady-State Pressure (psi)','dp (psi)','dt (s)'):
        if col in d:changes|=np.r_[True,d[col].to_numpy()[1:]!=d[col].to_numpy()[:-1]]
    run=np.cumsum(changes);time=d.index.to_numpy(float)*.25
    physical=(pf>=pc)&(pc>=0)&(cf>=0)&(cc>=0)&(cp>=0)&(t>0) if pressure_basis=='strict_mean' else (pf>0)&(pc>=0)&(cf>=0)&(cc>=0)&(cp>=0)&(t>0)
    b=SensorBatch(time,np.column_stack((q,ndp,factor)),('q','ndp','factor'),('m3/s','Pa','1'),
        'nrel_documented_0.25s_sample_index','nrel_SW30_4040','laboratory_measured',
        valid=np.broadcast_to(physical[:,None],(len(d),3)),episodes=np.array([f'{episode}:{r}' for r in run]),
        metadata={'area_m2':7.4,'permeate_gauge_pressure_assumption_pa':0.,'osmotic_model':'ideal NaCl approximation',
                  'temperature_factor':'FilmTec inverse Eq73/74, published empirical 273/298 constants',
                  'pressure_basis':pressure_basis,'feed_only_assumption_is_unqualified':pressure_basis!='strict_mean'})
    return b

def hp_table(sheet):
    path=DATA/'heatpump_propane'/'H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx'
    # Only the internally synchronized main logger, no index join to the separate superheat stream.
    d=pd.read_excel(path,sheet_name=sheet,header=0).iloc[1:,:13].copy()
    empty=d['Date'].isna()
    if (d.loc[empty].notna().any(axis=1)).any():raise ValueError('partial main heat-pump record lacks timestamp')
    d=d.loc[~empty].copy() # padding belongs only to the independent faster superheat logger
    d['Date']=pd.to_datetime(d['Date'],errors='coerce')
    if d.Date.isna().any():raise ValueError('unparseable main heat-pump clock')
    if not d.Date.is_monotonic_increasing or d.Date.duplicated().any():raise ValueError('invalid heat-pump time ordering')
    return d

def hp_batch(d,sheet):
    num=lambda name:pd.to_numeric(d[name],errors='coerce').to_numpy(float)
    load=10200. if sheet.endswith('10') else 12300. # experimental demand from Information sheet, not fault feature
    values=np.column_stack((num('Condenser_heat_duty')*1000,num('Compressor_power_consumption')*1000,
        num('Evaporator_saturation_temperature')+273.15,num('Condenser_saturation_temperature')+273.15,
        num('Liquid_line_refrigerant_temperature')+273.15,num('Compressor_outlet_temperature')+273.15,
        num('Refrigerant_Mass_flow')*.001,num('Compressor_speed'),np.full(len(d),load)))
    time=d.Date.to_numpy(dtype='datetime64[ns]').astype('int64')/1e9
    codes=d['Test code'].astype(str).to_numpy()
    # Known experimental boundaries (not a diagnosis feature) plus observed acquisition gaps.
    starts=np.r_[True,(codes[1:]!=codes[:-1])|(np.diff(time)>60)]
    start_times=np.maximum.accumulate(np.where(starts,time,-np.inf))
    eligible=(time-start_times)>=180. # frozen causal warmup for steady experimental screening
    b=SensorBatch(time,values,tuple(HP_CHANNELS.values()),('W','W','K','K','K','K','kg/s','1/s','W'),
        'tri_hp_naive_datetime_epoch_s','tri_hp_propane','laboratory_measured',
        valid=np.broadcast_to(eligible[:,None],values.shape),episodes=np.cumsum(starts),
        metadata={'refrigerant':'propane','mode':'heating','nominal_demands_w':[10200,12300],
            'source':'TRI-HP 5155136','warmup_s':180,'no_index_join_to_superheat':True})
    intensity=num('Fault intensity');known=np.isfinite(intensity)
    label=(intensity!=0)&(not sheet.startswith('NF'))
    return b,eligible&known,label,codes

def normal_partition(d):
    # Chronological blocks with 10% time gaps on both sides of calibration.
    t=d.Date.to_numpy(dtype='datetime64[ns]').astype('int64')/1e9 if 'Date' in d else d['Runtime (min)'].to_numpy(float)*60
    f=(t-t.min())/(t.max()-t.min())
    return dict(train=f<=.4,calibration=(f>=.5)&(f<=.7),evaluation=f>=.8,
                purge=((f>.4)&(f<.5))|((f>.7)&(f<.8)))
