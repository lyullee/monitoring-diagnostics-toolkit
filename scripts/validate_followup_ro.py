"""Fixed pressure-order QC on newly acquired experiments; never fault accuracy."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'research_support/public_data/gap_analysis_20261105/ro';OUT=ROOT/'outputs/diagnostic_gap_analysis'

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    policy=dict(criterion='finite feed/reject pressures and feed>=reject, no pressure swap/offset; quality only, no fault labels',
        source='https://mhkdr.openei.org/submissions/649',scope='previously unused experiments, same apparatus, not independent asset')
    (OUT/'ro_new_quality_protocol.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    raw=(DATA/'wec_sim.zip').read_bytes();files=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None
        for name in z.namelist():
            if name.endswith('.csv') and not name.startswith('__MACOSX/'):
                d=pd.read_csv(io.BytesIO(z.read(name)));diff=d['Feed Pressure (psi)'].to_numpy(float)-d['Reject Pressure (psi)'].to_numpy(float);valid=np.isfinite(diff)
                files.append(dict(file=name,rows=len(d),finite_pressure_rows=int(valid.sum()),pressure_order_ok=int((valid&(diff>=0)).sum()),median_feed_minus_reject_psi=float(np.median(diff[valid]))))
    result=dict(url='https://mhkdr.openei.org/files/649/wec_sim%20%281%29.zip',policy=policy,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
        files=files,status='obtained_quality_checked',source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),fault_accuracy=None,fault_recall=None,false_positive_rate=None)
    (OUT/'ro_new_quality.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    diagram=DATA/'process-flow-diagram.png'
    if diagram.exists():
        addendum=dict(source_url='https://mhkdr.openei.org/files/649/process-flow-diagram.png',file=str(diagram.relative_to(ROOT)),sha256=hashlib.sha256(diagram.read_bytes()).hexdigest(),
            observations=['Feed pressure point is downstream of feed pump and upstream of membrane vessel.','Reject pressure point is downstream of membrane and before back-pressure valve.','No intervening pump shown; diagram is not a scaled elevation drawing.'],
            conclusion='Document roles confirmed; calibration offset, pressure reference and elevation correction unresolved. No automatic swap or offset.')
        (OUT/'4_ro_quality_addendum.json').write_text(json.dumps(addendum,indent=2),encoding='utf-8')
    print(json.dumps(dict(rows=sum(x['rows'] for x in files),pressure_order_ok=sum(x['pressure_order_ok'] for x in files))))
if __name__=='__main__':main()
