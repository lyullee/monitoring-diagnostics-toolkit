"""External measured-data benchmark; no fault labels enter models or calibration.

Downloads are opt-in (--download), kept outside the package. Default reuses archives.
"""
from collections import Counter
from datetime import datetime,timezone
from html import escape
import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile
import numpy as np
from equipment_diagnostics import SensorBatch, ChillerPerformanceDiagnostic, ValveTrackingDiagnostic, __version__
from equipment_diagnostics.evaluation import binary_metrics

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'research_support'/'public_data'
OUT=ROOT/'outputs'/'public_validation'
URLS={
 'chiller/rp1043.zip':'https://ndownloader.figshare.com/files/52432007',
 'damadics/part1.zip':'https://iair.mchtr.pw.edu.pl/content/download/163/817/file/Lublin_all_data_part1.zip',
 'damadics/part2.zip':'https://iair.mchtr.pw.edu.pl/content/download/164/821/file/Lublin_all_data_part2.zip',
 'damadics/part3.zip':'https://iair.mchtr.pw.edu.pl/content/download/165/825/file/Lublin_all_data_part3.zip',
 'damadics/part4.zip':'https://iair.mchtr.pw.edu.pl/content/download/166/829/file/Lublin_all_data_part4.zip',
 'damadics/description.zip':'https://iair.mchtr.pw.edu.pl/content/download/161/809/file/damadics-lublin-data-description.zip',
 'column/data.zip':'https://zenodo.org/records/17628963/files/ContinuousDistillationData.zip?download=1',
}
PROTOCOL={
 'chiller':{'train':'normal.xls','calibration':'normal1.xls',
   'normal_test':['normal2','normal r','normal r1','normal eo','normal b','normal cf','normal cf2',
                  'normal cf3','normal cf4','normal cf5','normal cf6','normal nc'],
   'fault_test':{'Reduced evaporator water flow':['fwe10','fwe20','fwe30','fwe40'],
     'Refrigerant leak':['rl10','rl20','rl30','rl40'],
     'Refrigerant overcharge':['ro10','ro20','ro30','ro40'],
     'Condenser fouling':['cf6','cf12','cf20','cf30','cf45'],
     'Excess oil':['eo14','eo32','eo50'], 'Non-condensables in refrigerant':['nc1','nc2','nc3']},
   'water_density_kg_m3':998.2,'cp_j_kg_k':4180,'gpm_to_m3_s':0.003785411784/60,
   'steady_lookback_s':300,'max_water_temperature_range_k':1.,'persistence_s':30,
   'calibration_quantile':.99,'calibration_method':'normal-only common score threshold; default score threshold 1 also reported'},
 'valve':{'train':'29102001','calibration':'01112001',
   'test':['08112001','09112001','17112001','20112001','21112001','22112001'],
   'actuators':{'A1':[5,6],'A3':[27,28]},'delay_candidates_s':[0,1,2,3,4,5],
   'default_error_limit_fraction':.04,'calibration_quantile':.99,'persistence_s':3,
   'primary_target':'f16 supply-pressure-drop; other documented faults excluded from primary negatives',
   'background_label':'no documented injected fault, not independently maintenance-confirmed healthy'},
 'metrics':'sample-level conditional accuracy/recall/FPR + coverage + all-eligible fault detection; no point-adjustment',
 'test_policy':'Do not tune on test outcomes. Unknown samples never count as TN. No random row split.',
}
# Official description, Tables 3 and 5; inclusive seconds from midnight.
EVENTS=[('A1','09112001',57275,57550,'f16'),('A1','09112001',58830,58930,'f18'),
 ('A1','09112001',58520,58625,'f18'),('A1','17112001',54600,54700,'f18'),
 ('A1','17112001',56670,56770,'f16'),('A1','20112001',37780,38400,'f17'),
 ('A3','09112001',60650,60700,'f16'),('A3','09112001',60870,60960,'f16'),
 ('A3','17112001',57475,57530,'f16'),('A3','17112001',57675,57800,'f16'),
 ('A3','17112001',58150,58325,'f19')]


def score_threshold(result,batch,threshold,persistence):
    """A declared evaluation policy on raw scores; threshold 1 agrees with core alarms."""
    alarms=np.zeros(len(result.time_s),bool); since=None
    for i in range(len(alarms)):
        broken=(i==0 or not result.valid[i-1] or batch.time_s[i]-batch.time_s[i-1]>60
                or batch.episodes[i]!=batch.episodes[i-1])
        if broken: since=None
        if not result.valid[i] or result.scores[i]<=threshold: since=None; continue
        if since is None: since=batch.time_s[i]
        alarms[i]=batch.time_s[i]-since>=persistence
    return alarms


def aggregate(rows):
    return binary_metrics(*(np.concatenate([r[k] for r in rows]) for k in ('y','alarm','valid','eligible')))


def row_payload(key,source,y,alarm,result,eligible):
    return {'key':key,'source':source,'y':y,'alarm':alarm,'valid':result.valid,'eligible':eligible,
            'metrics':binary_metrics(y,alarm,result.valid,eligible),
            'reasons':dict(Counter(np.asarray(result.reasons)[eligible & ~result.valid]))}


def chiller(*, loader_only=False, extended_sensors=False):
    import xlrd
    import pandas as pd
    from CoolProp.CoolProp import PropsSI
    z=zipfile.ZipFile(DATA/'chiller'/'rp1043.zip'); p=PROTOCOL['chiller']; audit={}
    def load(name):
        sh=xlrd.open_workbook(file_contents=z.read(name)).sheet_by_name('Complete Data Set')
        header=sh.row_values(0)
        x=np.array([[v if isinstance(v,(float,int)) else np.nan for v in sh.row_values(i)]
                    for i in range(1,sh.nrows)])
        t=x[:,header.index('Time')]
        if not np.isfinite(t).all() or (np.diff(t)<0).any(): raise ValueError('Nonmonotonic chiller clock '+name)
        keep=np.r_[True,np.diff(t)>0]
        audit[name]={'raw_rows':len(t),'duplicate_timestamp_rows_removed':int((~keep).sum()),
                     'duplicate_policy':'keep first record at a repeated timestamp; no time sorting/interpolation'}
        x=x[keep]
        c={k:x[:,j] for j,k in enumerate(header)}
        t=c['Time']
        fahrenheit=lambda k:(c[k]-32)*5/9+273.15
        tei,teo,tci,tco=[fahrenheit(k) for k in ('TEI','TEO','TCI','TCO')]
        def saturation(k):
            pressure=c[k]*6894.757293168+101325
            out=np.full(len(t),np.nan)
            ok=(pressure>10000)&(pressure<4e6)&np.isfinite(pressure)
            out[ok]=PropsSI('T','P',pressure[ok],'Q',1,'R134a')
            return out
        flow=c['FWE']*p['gpm_to_m3_s']*p['water_density_kg_m3']
        values=np.column_stack((tei,teo,tco,saturation('PRE'),saturation('PRC'),flow,c['kW']*1000,tci))
        names=('tei','teo','tco','evap','cond','flow','power','tci')
        units=('K','K','K','K','K','kg/s','W','K')
        if extended_sensors:
            extra=np.column_stack((fahrenheit('TO_sump'),fahrenheit('TO_feed'),
                c['PO_feed']*6894.757293168+101325,c['PO_net']*6894.757293168,
                c['TRC_sub']*5/9,c['Tsh_suc']*5/9,c['Tsh_dis']*5/9,
                c['FWC']*p['gpm_to_m3_s']*p['water_density_kg_m3']))
            values=np.column_stack((values,extra))
            names=(*names,'oil_sump','oil_feed','oil_feed_p','oil_net_p','subcool','suction_sh','discharge_sh','cw_flow')
            units=(*units,'K','K','Pa','Pa','K','K','K','kg/s')
        # Causal steady-state gate; no fault identity, reported COP or fault flags used.
        temps=pd.DataFrame(np.column_stack((tei,teo,tci,tco)),index=pd.to_timedelta(t,unit='s'))
        roll=temps.rolling('300s',min_periods=25)
        ranges=(roll.max()-roll.min()).to_numpy()
        eligible=(np.isfinite(ranges).all(axis=1)&(ranges<=1).all(axis=1)&(t-t[0]>=300)
                  &(c['kW']>1)&(c['FWE']>1)&(tei>teo))
        batch=SensorBatch(t,values,names,units,'rp1043_elapsed_s','rp1043_90ton','laboratory_measured',
            valid=np.broadcast_to(eligible[:,None],values.shape),
            metadata={'source_file':name,'quality_gate':'causal 300s water-temperature range <=1K',
              'density_kg_m3_assumption':998.2,'refrigerant':'R134a','saturation_basis':'measured psig + 101325 Pa; CoolProp Q=1'})
        return batch,eligible
    if loader_only: return load,audit
    channels=dict(chilled_in='tei',chilled_out='teo',cooling_out='tco',evaporating_temperature='evap',
                  condensing_temperature='cond',chilled_flow='flow',electric_power='power')
    train,traineligible=load('Chiller Data/Benchmark Tests/'+p['train'])
    model=ChillerPerformanceDiagnostic(channels,persistence_s=30).fit(train)
    cal,caleligible=load('Chiller Data/Benchmark Tests/'+p['calibration'])
    calibration=model.score(cal)
    if calibration.valid.sum()<10: raise ValueError('Too few chiller calibration samples')
    threshold=max(1.,float(np.nextafter(np.quantile(calibration.scores[calibration.valid],.99),np.inf)))
    specs=[('Chiller Data/Benchmark Tests/'+n+'.xls',False,'normal') for n in p['normal_test']]
    specs += [('Chiller Data/'+category+'/'+n+'.xls',True,category) for category,names in p['fault_test'].items() for n in names]
    policies={'default':[],'normal_calibrated':[]}
    predictions=[]
    for name,fault,category in specs:
        b,eligible=load(name); r=model.score(b); y=np.full(len(b.time_s),fault,bool)
        for policy,cut in [('default',1.),('normal_calibrated',threshold)]:
            a=score_threshold(r,b,cut,30)
            if policy=='default': np.testing.assert_array_equal(a,r.alarms)
            policies[policy].append(row_payload(category,name,y,a,r,eligible))
        a=policies['normal_calibrated'][-1]['alarm']
        predictions.extend(zip([name]*len(y),b.time_s,y,eligible,r.valid,r.scores,a))
        print('chiller',Path(name).stem,'eligible',int(eligible.sum()),'valid',int(r.valid.sum()),flush=True)
    write_predictions('chiller',predictions)
    reports={}
    for policy,rows in policies.items():
        bycategory={cat:aggregate([r for r in rows if r['key']==cat]) for cat in sorted({r['key'] for r in rows})}
        reports[policy]={'metrics':aggregate(rows),'by_fault_type':bycategory,
            'files':[{'file':r['source'],'category':r['key'],'metrics':r['metrics'],'unknown_reasons':r['reasons']} for r in rows]}
    return {'module':'chiller_performance','status':'evaluated_laboratory_measured',
        'source':'https://figshare.com/articles/dataset/Chiller_operation_data_set/28435232',
        'provenance_note':'Public redistribution by Zengrui Tian, labeled ASHRAE RP-1043; not downloaded from original ASHRAE distribution. CC0 stated by uploader; original provenance not independently authenticated.',
        'train_file':p['train'],'calibration_file':p['calibration'],'test_files':len(specs),
        'reference':model.reference,'calibrated_score_threshold':threshold,'data_audit':audit,
        'calibration_valid':int(calibration.valid.sum()),'policies':reports,
        'limitations':['One physical chiller; no cross-machine generalization test.',
          'COP uses assumed constant water density/cp; pressure-derived R134a saturation has pressure-reference and purity assumptions.',
          'Noncondensable faults violate the pure-refrigerant pressure/saturation assumption; report separately.',
          'Repeated time samples are correlated; no IID confidence interval claimed.',
          'Only predeclared steady operating samples evaluated; coverage and excluded counts reported.',
          'Normal/fault assignment is run-level experimental documentation, not reported Active Fault/Unit Status.']}


def write_predictions(name,rows):
    with (OUT/(name+'_predictions.csv')).open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['source','time_s','fault_label','eligible','valid','score','alarm'])
        for source,t,y,e,v,s,a in rows: w.writerow([source,t,int(y),int(e),int(v),s if np.isfinite(s) else '',int(a)])


def valves():
    archives=[zipfile.ZipFile(DATA/'damadics'/f'part{i}.zip') for i in range(1,5)]
    lookup={Path(n).stem:(z,n) for z in archives for n in z.namelist() if n.endswith('.txt')}
    cache={}
    def load(date):
        if date not in cache:
            z,n=lookup[date]; cache[date]=np.loadtxt(io.BytesIO(z.read(n)))
        return cache[date]
    p=PROTOCOL['valve']; rows={'default':[],'normal_calibrated':[]}; events=[]; tuning={}; preds=[]
    for asset,(ci,xi) in p['actuators'].items():
        def batch(date):
            x=load(date)
            return SensorBatch(x[:,0],x[:,[ci,xi]]/100,('command','position'),('1','1'),
                'damadics_seconds_from_midnight',asset,'historian_measured',
                metadata={'source_date_ddmmyyyy':date,'original_columns_one_based':[ci+1,xi+1],
                          'fraction_basis':'both source channels are percent closing; divide by 100; no clipping'})
        channels={'command':'command','position':'position'}
        train=batch(p['train']); cal=batch(p['calibration'])
        maes=[]
        for delay in p['delay_candidates_s']:
            m=ValveTrackingDiagnostic(channels,error_limit_fraction=.04,delay_s=delay)
            r=m.score(train); maes.append(float(np.mean(np.abs(r.metrics['tracking_error_fraction'][r.valid]))))
        delay=p['delay_candidates_s'][int(np.argmin(maes))]
        r=ValveTrackingDiagnostic(channels,error_limit_fraction=.04,delay_s=delay).score(cal)
        limit=max(.005,float(np.nextafter(np.quantile(np.abs(r.metrics['tracking_error_fraction'][r.valid]),.99),np.inf)))
        if limit>=1: raise ValueError('Invalid valve calibration limit')
        tuning[asset]={'train_delay_mae':maes,'delay_s':delay,'error_limit_fraction':limit,
                       'calibration_valid':int(r.valid.sum())}
        for date in p['test']:
            b=batch(date); t=b.time_s
            primary=np.zeros(len(t),bool); other=np.zeros(len(t),bool)
            dayevents=[e for e in EVENTS if e[0]==asset and e[1]==date]
            for _,_,start,end,code in dayevents:
                target=primary if code=='f16' else other
                target |= (t>=start)&(t<=end)
            for policy,lim,d in [('default',.04,0),('normal_calibrated',limit,delay)]:
                model=ValveTrackingDiagnostic(channels,error_limit_fraction=lim,delay_s=d,persistence_s=3)
                r=model.score(b)
                rows[policy].append(row_payload(asset,asset+'/'+date,primary,r.alarms,r,~other))
                if policy=='normal_calibrated':
                    preds.extend(zip([asset+'/'+date]*len(t),t,primary,~other,r.valid,r.scores,r.alarms))
                    for _,_,start,end,code in dayevents:
                        window=(t>=start)&(t<=end)
                        hits=np.flatnonzero(window & r.alarms & r.valid)
                        events.append({'asset':asset,'date':date,'start_s':start,'end_s':end,'fault':code,
                            'detected':bool(len(hits)),'delay_s':None if not len(hits) else float(t[hits[0]]-start),
                            'valid_samples':int(np.sum(window&r.valid)),'samples':int(window.sum()),
                            'alarm_samples':int(np.sum(window&r.valid&r.alarms))})
            print('valve',asset,date,flush=True)
    write_predictions('valve',preds)
    reports={policy:{'metrics':aggregate(group),
        'by_actuator':{a:aggregate([r for r in group if r['key']==a]) for a in p['actuators']},
        'files':[{'file':r['source'],'metrics':r['metrics'],'unknown_reasons':r['reasons']} for r in group]}
        for policy,group in rows.items()}
    relevant=[e for e in events if e['fault']=='f16']
    return {'module':'valve_tracking','status':'evaluated_real_plant_measured',
        'source':'https://iair.mchtr.pw.edu.pl/Damadics','tuning':tuning,'policies':reports,'events':events,
        'primary_event_detection':{'detected':sum(e['detected'] for e in relevant),'total':len(relevant)},
        'limitations':['Normal means no documented injected fault, not certified healthy operation; natural/unrecorded faults may contaminate FPR.',
            'Primary sensitivity is for six f16 supply-pressure-drop events only; bypass/pressure/sensor faults are not declared valve-position faults.',
            'Other documented fault windows are excluded from primary negatives and listed individually, never silently called normal.',
            'No point-adjustment: detecting one event does not relabel its whole window as detected.',
            'Two actuators in one factory; temporal dependence and uncertain fault-window boundaries remain.',
            'Some samples are out of physical range/missing; no clipping or interpolation; coverage reported.']}


UNVERIFIED=[
 {'module':'mass_balance','status':'not_evaluated_missing_required_channels',
  'candidate':'https://pmc.ncbi.nlm.nih.gov/articles/PMC13683349/',
  'reason':'Real two-tank experiment has level and pump command, but lacks measured inlet/outlet flows. Pump command is not a flow sensor; deriving both flows from level would circularly erase residuals.'},
 {'module':'boiler_mass_balance','status':'not_evaluated_missing_inventory',
  'candidate':'https://iair.mchtr.pw.edu.pl/Damadics',
  'reason':'DAMADICS has boiler feed/steam flow and level percent, but no qualified total steam/water mass or complete blowdown boundary. LBNL boiler public package is simulated.'},
 {'module':'heat_exchanger','status':'not_evaluated_incompatible_or_incomplete_data',
  'candidate':'https://archive.ics.uci.edu/dataset/447/condition+monitoring+of+hydraulic+systems',
  'reason':'UCI cooler fault labels are real, but the required two-side temperatures/flows are incomplete. RP1043 evaporator/condenser have phase change, outside this single-phase UA module. A 2025 refinery heat-exchanger study (doi:10.3390/s25164936) has the right sensor types but raw data are available only on request.'},
 {'module':'hydraulic_resistance','status':'not_evaluated_missing_compatible_labels',
  'candidate':'https://dataverse.no/dataset.xhtml?persistentId=doi:10.18710/PQ0UWZ',
  'reason':'Plugging experiment uses multiphase ice-in-decane slurry, outside fixed-viscosity single-phase correction. DAMADICS has pressure/flow but changing valve opening changes geometry; no fixed-geometry blockage labels. Polymer filter dataset lacks filter pressure measurements.'},
 {'module':'vaporizer','status':'not_evaluated_no_downloadable_labeled_series_identified',
  'candidate':'https://doi.org/10.3390/pr11113143',
  'reason':'Operational AAV prediction study found, but no obtained public raw temperature/flow series with independent fault truth and a separately qualified normal prediction model. No synthetic predicted temperature substituted.'},
 {'module':'ro_membrane','status':'not_evaluated_missing_fault_labels',
  'candidate':'https://catalog.data.gov/dataset/experimental-wave-desalination-data-with-variable-feed-and-pressure-input',
  'reason':'Public dynamic RO characterization data and transport-property experiments found; their controlled operating changes are not independently annotated membrane-fouling faults. No complete compatible healthy/fault split obtained.'},
 {'module':'column_hydraulics','status':'not_evaluated_missing_internal_loading',
  'candidate':'https://zenodo.org/records/17628963',
  'reason':'Downloaded 28-run real continuous-distillation archive and inspected all three FeaturesOverview files. Paper identifies packing DP but distributed feature descriptions also ambiguously label these as reboiler DP. Internal vapor mass flow is absent; feed/distillate/net buffer-mass derivatives are not both internal phase loadings. No unqualified flow reconstruction or zero exponent substituted to claim full-module validation.'},
 {'module':'steam_trap','status':'not_evaluated_raw_data_not_public',
  'candidate':'https://www.mdpi.com/1424-8220/26/21/6763',
  'reason':'Recent real pharmaceutical-plant temperature/ultrasound paper explicitly keeps raw DatasetI/DatasetZ confidential. Generic MIMII valve sound does not supply steam reference temperature, supply state and trap-fault truth.'},
]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--download',action='store_true'); ap.add_argument('--only',choices=['chiller','valve'])
    args=ap.parse_args(); OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'protocol.json').write_text(json.dumps(PROTOCOL,indent=2),encoding='utf-8')
    for relative,url in URLS.items():
        if args.only=='chiller' and not relative.startswith('chiller'): continue
        if args.only=='valve' and not relative.startswith('damadics'): continue
        path=DATA/relative
        if not path.exists():
            if not args.download: raise FileNotFoundError(f'{path}: run --download first')
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.download'); urllib.request.urlretrieve(url,temporary); temporary.replace(path)
        if not zipfile.is_zipfile(path): raise ValueError('Invalid/incomplete archive: '+str(path))
    if not args.only or args.only=='chiller':
        r=chiller(); (OUT/'chiller_results.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    if not args.only or args.only=='valve':
        r=valves(); (OUT/'valve_results.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    evaluated=[json.loads((OUT/f'{name}_results.json').read_text(encoding='utf-8')) for name in ('chiller','valve') if (OUT/f'{name}_results.json').is_file()]
    result={'schema':'equipment-diagnostics.public-validation.v1','utc':datetime.now(timezone.utc).isoformat(),
        'version':__version__,'protocol':PROTOCOL,'evaluated':evaluated,'not_evaluated':UNVERIFIED,
        'dependencies':{p:importlib.metadata.version(p) for p in ('numpy','pandas','xlrd','CoolProp')},
        'files':{relative:{'source_url':url,'bytes':(DATA/relative).stat().st_size,
            'sha256':hashlib.sha256((DATA/relative).read_bytes()).hexdigest()} for relative,url in URLS.items() if (DATA/relative).is_file()},
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]}}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    render(result)
    for r in evaluated:
        print(r['module'],json.dumps(r['policies']['normal_calibrated']['metrics']),flush=True)


def render(result):
    pct=lambda v:'산출 불가' if v is None else f'{v*100:.2f}%'
    rows=''
    for r in result['evaluated']:
        for policy,v in r['policies'].items():
            m=v['metrics']; label='기본 설정' if policy=='default' else '정상 데이터로 보정'
            values=[r['module'],label,m['eligible'],m['valid'],pct(m['coverage']),pct(m['accuracy_valid']),
                pct(m['recall_valid']),pct(m['false_positive_rate_valid']),pct(m['fault_detection_all_eligible']),
                pct(m['coverage_all_rows'])]
            rows+='<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in values)+'</tr>'
    missing=''.join('<tr><td>'+escape(r['module'])+'</td><td>'+escape(r['reason'])+'</td><td><a href="'+escape(r['candidate'])+'">검토 자료</a></td></tr>' for r in result['not_evaluated'])
    details=''.join('<h2>'+escape(r['module'])+'</h2><pre>'+escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre>' for r in result['evaluated'])
    html=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>공개 실측 데이터 검증</title>
<style>body{{font:15px/1.6 system-ui;max-width:1450px;margin:30px auto;padding:20px;color:#1d3040}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #c9d4dd;padding:10px;text-align:left}}th{{background:#e8f0f7}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.note{{background:#fff2d5;padding:18px}}</style>
<h1>공개 실제 설비·실험 데이터 검증</h1><p>{escape(result['utc'])} · v{escape(result['version'])}</p>
<p class="note">냉동기 1대의 실험 자료와 한 공장의 밸브 2개에서 평가했습니다. 정확도·검출률·오경보율은 판단 가능한 표본에서 계산합니다.
UNKNOWN을 정상 정답으로 세지 않으며 판단률과 전체 평가 가능 고장 표본 대비 검출률을 함께 표시합니다.
밸브의 주 평가 고장은 f16 공급압력 저하 6건이고, 배경 구간은 정비로 정상 확인된 구간이 아니라 문서상 주입 고장이 없는 구간입니다.
시계열 표본은 서로 상관되므로 표본 수를 독립 실험 횟수로 해석하지 않습니다. 고장 종류 분류 정확도가 아닌 정상/이상 이진 스크리닝 평가입니다.</p>
<table><tr><th>모듈</th><th>설정</th><th>평가 대상 표본</th><th>판단 표본</th><th>대상 중 판단률</th><th>정확도</th><th>검출률</th><th>오경보율</th><th>전체 대상 고장 검출률</th><th>원본 전체 중 판단률</th></tr>{rows}</table>
<p>정확도=(TP+TN)/(TP+TN+FP+FN), 검출률=TP/(TP+FN), 오경보율=FP/(FP+TN)입니다.
정상 데이터가 많은 밸브는 정확도만으로 평가하면 과대평가되므로 balanced accuracy·precision·6건의 이벤트별 검출 결과도 아래 상세에 제시합니다.
냉동기 표에서 대상은 온도 안정 구간이며, 원본 전체 대비 판단률도 마지막 열에 별도로 표시했습니다.</p>
<h2>데이터·센서·정답 부족으로 평가하지 못한 모듈</h2><p>아래는 이번 조사와 현재 구현에서 미검증이라는 뜻이며, 공개 데이터가 전혀 없다는 뜻이 아닙니다.</p>
<table><tr><th>모듈</th><th>구체적 사유</th><th>출처</th></tr>{missing}</table>
<h2>평가 방법</h2><p>운전 파일/날짜 단위로 학습·보정·평가를 분리했습니다. 임계값은 정상 보정 데이터의 99백분위수로만 정하며 고장 평가 결과로 조정하지 않습니다.
기본 설정의 결과도 함께 공개합니다. 냉동기는 인과적 300초 온도 안정 구간을 대상으로 하고, 밸브는 명령과 실측 위치를 같은 닫힘 비율로 변환합니다.
이벤트 한 번 검출로 전체 구간을 정답 처리하는 point-adjustment는 적용하지 않습니다.</p>
<p>원본 압축파일 SHA256, 파일별 혼동행렬, 고장별 성능, UNKNOWN 사유, 이벤트별 검출 지연 및 전체 프로토콜은 results.json과 아래 상세에 보존했습니다.</p>
{details}</html>'''
    (OUT/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__': main()
