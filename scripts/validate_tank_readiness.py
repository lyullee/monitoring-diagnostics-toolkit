"""Rank7 measured calibration/clock audit; no invented quantitative leak labels."""
import hashlib,io,json,re,zipfile
from pathlib import Path
import numpy as np
from equipment_diagnostics import SensorBatch,calibrated_level
from inspect_acquired_actual_data import strict_rows

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs/completion_7_13/tank'
RAW=ROOT/'research_support/public_data/acquisition_20261105/tank_three/repository.zip'
CAL={1:(.2849,.0547),2:(.2866,.0608),3:(.2806,.0654)}
def seconds(a):
    # Header says mSec, actual values are fractional seconds (0.719, not719).
    return a[:,0]*3600+a[:,1]*60+a[:,2]+a[:,3]

def main():
    OUT.mkdir(parents=True,exist_ok=True);z=zipfile.ZipFile(RAW); records=[]
    for name in z.namelist():
        if not name.endswith('.xlsx'):continue
        rows,_=strict_rows(z.read(name)); a=np.array([[float(x) if x else np.nan for x in row] for row in rows[2:]])
        t=seconds(a[:,:4]);entry=dict(file=name,rows=len(a),member_sha256=hashlib.sha256(z.read(name)).hexdigest(),
            nonincreasing_system_clock_steps=int(np.sum(np.diff(t)<=0)),system_step_median_s=float(np.median(np.diff(t))))
        if 'pressure_sensor' in name:
            sensor=seconds(a[:,5:9]);dt=sensor-t;entry.update(sensor_minus_system_s=dict(min=float(dt.min()),median=float(np.median(dt)),max=float(dt.max())),
                raw_voltage_range=[float(a[:,10].min()),float(a[:,10].max())])
            ident=int(re.search(r'tank(\d)',name)[1]);slope,offset=CAL[ident]
            # Transform only one sensor on its OWN clock; never index-join flows.
            b=SensorBatch(sensor,a[:,10:11],('voltage',),('V',),'sensor_timestamp_unaligned',f'tank{ident}',name)
            lo,hi=entry['raw_voltage_range']
            r=calibrated_level(b,'voltage',slope_m_v=slope,offset_m=offset,qualified_voltage_range_v=(lo,hi))
            h,good=r.column('level_m','m');assert np.allclose(h,slope*a[:,10]+offset,rtol=0,atol=1e-15)
            entry.update(calibration=dict(slope_m_v=slope,offset_m=offset,source='creator MLX report; calibration uncertainty not supplied'),
                level_range_m=[float(h.min()),float(h.max())],transformed_rows=int(good.sum()),
                range_note='observed span only, not a metrologically qualified extrapolation range')
        if 'leakage' in name:
            # Column5 is this-second count, column6 cumulative count; the MLX
            # comments inconsistently refer to pulse/sec versus total count.
            c=a[:,4];total=a[:,5]
            onset=np.flatnonzero(c>0)
            entry.update(positive_count_rows=int((c>0).sum()),first_positive_count_system_s=None if not len(onset) else float(t[onset[0]]),
                cumulative_decreases=int((np.diff(total)<0).sum()),cumulative_increment_vs_this_second_max_abs=float(np.max(abs(np.diff(total)-c[1:]))))
        records.append(entry)
    result=dict(source='https://github.com/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data',
        archive_sha256=hashlib.sha256(RAW.read_bytes()).hexdigest(),streams=records,
        qualitative_progress='Creator pressure-to-level coefficients recovered and replayed on nine pressure streams.',
        quantitative_mass_balance_metrics=None,
        blockers=['Flow pulse-to-volume calibration and reliability are not qualified.',
            'Sensor and system timestamps differ; a documented acquisition/availability clock model is needed before causal fusion.',
            'Drum/tank cross-section and density uncertainty needed to turn level into inventory mass.',
            'Leak pulse onset is not independently metered kg/s ground truth.'],
        sensitivity=[dict(window_s=w,inventory_bound_kg=e,flow_bound_sum_kg_s=.02,
            residual_error_bound_kg_s=2*e/w+.02,detectable_loss_lower_bound_rule='loss > configured engineering limit + residual error bound')
            for w in (60,300,900) for e in (.1,1,10)])
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(streams=len(records),pressure_streams=sum('calibration' in r for r in records),
        transformed_rows=sum(r.get('transformed_rows',0) for r in records),quantitative_metrics=None),indent=2))
if __name__=='__main__':main()
