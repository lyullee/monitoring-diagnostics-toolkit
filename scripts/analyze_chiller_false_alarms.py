"""Attribute old frozen-model alarms; no training/calibration or threshold changes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import ChillerPerformanceDiagnostic
from validate_public_data import chiller,PROTOCOL,DATA
from validate_chiller_stages import CHANNELS,EXTRA

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'remaining_modules'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    frozen_path=ROOT/'outputs'/'chiller_stages'/'frozen_development.json'
    frozen=json.loads(frozen_path.read_text(encoding='utf-8'))
    previous=json.loads((frozen_path.parent/'results.json').read_text(encoding='utf-8'))
    assert digest(DATA/'chiller'/'rp1043.zip')==frozen['dataset_sha256']
    load,_=chiller(loader_only=True,extended_sensors=True);models={}
    for stage in (1,2,3):
        channels={**CHANNELS,'cooling_in':'tci',**EXTRA}
        if stage==3:channels['cooling_flow']='cw_flow'
        saved=frozen['stages'][str(stage)]
        models[stage]=ChillerPerformanceDiagnostic(channels,**saved['params'],persistence_s=30).set_reference(saved['reference'])
    snapshots={str(k):json.dumps(m.reference,sort_keys=True) for k,m in models.items()}
    totals={str(k):Counter() for k in models};normal_counts={str(k):Counter() for k in models};files=[]
    for name in PROTOCOL['chiller']['normal_test']:
        b,e=load('Chiller Data/Benchmark Tests/'+name+'.xls');item={'file':name,'stages':{}}
        for stage,m in models.items():
            r=m.score(b);hit=e&r.valid&r.alarms;names=sorted(k for k in r.metrics if k.startswith('channel_') and k.endswith('_score'))
            active=np.column_stack([r.metrics[k][hit] for k in names])
            counts=Counter(names[i].removeprefix('channel_').removesuffix('_score') for i in np.argmax(active,axis=1)) if hit.any() else Counter()
            totals[str(stage)].update(counts);normal_counts[str(stage)].update(valid=int(np.sum(e&r.valid)),FP=int(hit.sum()))
            item['stages'][str(stage)]={'valid_normal_samples':int(np.sum(e&r.valid)),'false_alarm_samples':int(hit.sum()),
                'dominant_channel_counts':dict(counts),'dominant_channel_definition':'largest raw channel score at each emitted false alarm; ties use alphabetic channel order'}
        files.append(item);print(name,flush=True)
    for stage,c in normal_counts.items():
        old=previous['comparison'][stage]['by_category']['normal']
        assert c['valid']==old['valid'] and c['FP']==old['FP']
    assert snapshots=={str(k):json.dumps(m.reference,sort_keys=True) for k,m in models.items()}
    result={'schema':'equipment-diagnostics.chiller-false-alarm-attribution.v1','model_version':'0.6.0 frozen models',
        'evidence_type':'reanalysis_of_previously_examined_experimental_data','development_use_only':True,
        'old_normal_counts_reproduced':True,'reference_models_unchanged':True,'source_model_sha256':digest(frozen_path),
        'normal_counts':{k:dict(v) for k,v in normal_counts.items()},
        'dominant_channel_counts':{k:dict(v.most_common()) for k,v in totals.items()},'files':files,
        'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]},
        'limits':['Dominance is a score attribution, not proof of a failed sensor or physical root cause.',
            'No operating-mode labels inferred from healthy test filenames for training or gating.',
            'Existing normal/test files are development evidence now; new independent data needed for final qualification.',
            'No new thresholds, fitted models, or improved chiller performance claimed.']}
    (OUT/'chiller_attribution.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['dominant_channel_counts'],indent=2))

if __name__=='__main__':main()
