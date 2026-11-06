"""Package original source only and smoke-test the built wheel outside this checkout."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import subprocess
import sys
import tempfile
import zipfile
from equipment_diagnostics import __version__

# The pre-public distribution name and historical hash-bound packaging checks
# below are retained for research snapshots. Public releases use standard
# wheel/sdist metadata and a separate membership/continuity audit.
if tuple(map(int, __version__.split('.'))) >= (0, 17, 0):
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-m', 'build'], cwd=root, check=True)
    subprocess.run([sys.executable, str(root/'scripts/release_audit.py')], cwd=root, check=True)
    raise SystemExit(0)

root = Path(__file__).resolve().parents[1]
out = root/"outputs"/"python_dist"
wheel = out/f"equipment_diagnostics-{__version__}-py3-none-any.whl"
if not wheel.is_file():
    raise SystemExit("Build the wheel first: python -m pip wheel --no-deps --wheel-dir outputs/python_dist .")
with tempfile.TemporaryDirectory(prefix="equipment_diagnostics_wheel_") as temporary:
    target = Path(temporary)/"installed"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)],
                   check=True, capture_output=True, text=True)
    code = '''import sys,json,pathlib
import numpy as np
sys.path.insert(0,sys.argv[1])
import equipment_diagnostics as ed
from equipment_diagnostics.chiller_staged import AUX_KEYS
assert len(AUX_KEYS)==7
from equipment_diagnostics.quick_improvements import first_order_step
assert abs(first_order_step(.2,.8,.8,2,2)-(.8-.6*np.exp(-1)))<1e-12
from equipment_diagnostics.operating_models import RO_UNITS
assert RO_UNITS['membrane_temperature']=='K'
assert pathlib.Path(ed.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
b=ed.SensorBatch(np.arange(5.),np.column_stack((np.full(5,270.),np.full(5,290.),np.ones(5))),
 ("out","pred","flow"),("K","K","kg/s"),"clock","asset","synthetic")
r=ed.VaporizerDiagnostic({"outlet_temperature":"out","predicted_temperature":"pred","mass_flow":"flow"},shortfall_limit_k=5).score(b)
assert r.alarms.all()
assert ed.VaporizerDiagnostic({"outlet_temperature":"out","mass_flow":"flow"},shortfall_limit_k=5,
 minimum_outlet_k=280,prediction_mode="minimum_only").score(b).alarms.all()
json.dumps(r.to_dict(),allow_nan=False)
assert len(ed.DIAGNOSTICS)==11
assert ed.HeatPumpPerformanceDiagnostic.kind=='heat_pump_performance'
assert ed.FilterServiceRiskModel.kind=='filter_service_risk'
assert ed.FilterRiskClassifier.kind=='filter_risk_classifier'
assert ed.TemporalEvidenceDiagnostic.kind=='temporal_evidence'
assert ed.FilterRiskEnsemble.kind=='filter_risk_ensemble'
assert ed.ResidualCoherenceDiagnostic.kind=='residual_coherence'
assert ed.WetCoilAirsideDiagnostic.kind=='wet_coil_airside'
assert ed.LoadConditionedPressureDiagnostic.kind=='load_conditioned_filter_pressure'
assert ed.SignedResidualCUSUM.kind=='signed_residual_cusum'
assert ed.ConditionalResidualDiagnostic.kind=='conditional_normal_residual'
assert ed.WindowChangeDiagnostic.kind=='window_residual_change'
assert float(ed.evaporator_conductance_proxy(10000,3000,278,283)['conductance_proxy_w_k'])==1400
assert float(ed.horizontal_cylinder_liquid_volume(1,radius_m=1,length_m=2))>3
v=ed.PiecewiseVaporizer(saturation_temperature_k=300,latent_heat_j_kg=100000,
 liquid_cp_j_kg_k=2000,vapor_cp_j_kg_k=1000,ua_w_k=100,property_basis_id='smoke')
assert abs(float(v.predict(1,0,350)['vapor_fraction'])-.05)<1e-12
print("Installed wheel smoke passed; diagnostic kinds:",len(ed.DIAGNOSTICS))
'''
    run = subprocess.run([sys.executable, "-I", "-c", code, str(target)], cwd=temporary,
                         check=True, capture_output=True, text=True)
    print(run.stdout)
source = out/f"equipment-diagnostics-{__version__}-source.zip"
evidence = root/"outputs"/"python_verification"
integration = json.loads((evidence/"integration_results.json").read_text(encoding="utf-8"))
(root/"docs"/"UPSTREAM_REVISIONS.json").write_text(json.dumps({
    "upstream_revisions": integration["upstream_revisions"],
    "scope": integration["scope"], "rotorvibe": integration["rotorvibe"]}, indent=2), encoding="utf-8")
files = [root/n for n in ("pyproject.toml", "README.md", "MANIFEST.in", ".gitignore")]
for directory in ("src", "tests", "docs", "examples", "scripts"):
    files.extend(p for p in (root/directory).rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and not any(s.endswith('.egg-info') for s in p.parts))
with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as z:
    for file in sorted(set(files)):
        z.write(file, str(Path('equipment-diagnostics')/file.relative_to(root)))
manifest = {"schema": "equipment-diagnostics.release.v1", "version": __version__,
            "wheel_smoke": run.stdout.strip(),
            "artifacts": {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in (wheel, source)},
            "excluded": ["external checkouts", "research PDFs", "raw observations", "virtual environment"],
            "scope": "Original screening code with numerical/object checks and a bounded public measured-data benchmark; no general field qualification."}
physics_path = root/"outputs"/"physics_verification"/"results.json"
if physics_path.exists():
    physics = json.loads(physics_path.read_text(encoding="utf-8"))
    manifest["physics_verification"] = {
        "version": physics["version"], "passed": physics["passed"], "tests": physics["tests"],
        "successful": physics["successful"], "scope": physics["scope"],
        "results_sha256": hashlib.sha256(physics_path.read_bytes()).hexdigest()}
(evidence/"release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
stages_path = root/"outputs"/"staged_verification"/"results.json"
if stages_path.exists():
    stages = json.loads(stages_path.read_text(encoding="utf-8"))
    manifest["six_stage_verification"] = {k: stages[k] for k in
        ("version", "passed", "tests", "unique_test_ids", "successful", "scope")}
    manifest["six_stage_verification"]["results_sha256"] = hashlib.sha256(stages_path.read_bytes()).hexdigest()
    (evidence/"release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
public_path = root/"outputs"/"public_validation"/"results.json"
if public_path.exists():
    public = json.loads(public_path.read_text(encoding="utf-8"))
    manifest["public_measured_data_evaluation"] = {
        "version": public["version"], "utc": public["utc"],
        "evaluated_modules": [r["module"] for r in public["evaluated"]],
        "not_evaluated_modules": [r["module"] for r in public["not_evaluated"]],
        "results_sha256": hashlib.sha256(public_path.read_bytes()).hexdigest(),
        "scope": "One laboratory chiller public redistribution and two plant valves; metrics and limitations in public_validation/results.json."}
    (evidence/"release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
upgrade_path = root/"outputs"/"chiller_upgrade"/"results.json"
if upgrade_path.exists():
    upgrade = json.loads(upgrade_path.read_text(encoding="utf-8"))
    audit_path = upgrade_path.with_name('independent_audit.json')
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256(upgrade_path.read_bytes()).hexdigest()
    manifest['chiller_upgrade_evaluation'] = {
        'version':upgrade['version'],'baseline_counts_reproduced':upgrade['baseline_counts_reproduced'],
        'before_calibrated':upgrade['comparison']['before_calibrated']['metrics'],
        'after_calibrated':upgrade['comparison']['after_calibrated']['metrics'],
        'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'scope':'Same 35 held-out files as prior development round; not a new blind or cross-machine test.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
chiller_stages_path = root/'outputs'/'chiller_stages'/'results.json'
if chiller_stages_path.exists():
    staged = json.loads(chiller_stages_path.read_text(encoding='utf-8'))
    audit = json.loads(chiller_stages_path.with_name('independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256(chiller_stages_path.read_bytes()).hexdigest()
    if staged['version']==__version__:
        for name,h in staged['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    manifest['chiller_staged_evaluation'] = {
        'version':staged['version'],'baseline_counts_reproduced':staged['baseline_counts_reproduced'],
        'stages':{k:v['metrics'] for k,v in staged['comparison'].items()},
        'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'deployment_status':'Additional stages experimental; large measured false-positive rates; retain stage 0 for this comparison.',
        'scope':'Reused 35 experimental-chiller runs. Separate normal train/calibration. Not new blind or field qualification.'}
    verification_dirs={'0.6.0':'chiller_stages','0.7.0':'quick_improvements','0.8.0':'remaining_modules','0.9.0':'acquired_modules_validation','0.10.0':'filter_heatpump_improvement','0.11.0':'filter_heatpump_operating_points','0.12.0':'diagnostic_followup','0.13.0':'stage56_ensemble','0.14.0':'completion_7_13','0.15.0':'literature_improvement','0.16.0':'two_target_improvement'}
    regression_path=root/'outputs'/verification_dirs[__version__]/'regression.xml'
    suites=ET.parse(regression_path).getroot().findall('testsuite')
    assert suites and all(int(s.get(k,'0'))==0 for s in suites for k in ('failures','errors','skipped'))
    assert integration['exit_code']==0
    current_files=sorted((root/'src'/'equipment_diagnostics').glob('*.py'))
    assert hashlib.sha256(b''.join(f.name.encode()+f.read_bytes() for f in current_files)).hexdigest()==integration['source_sha256']
    manifest['current_regression']={
        'version':__version__,'non_integration_tests':sum(int(s.get('tests')) for s in suites),
        'integration_output':integration['pytest_output'],
        'regression_xml_sha256':hashlib.sha256(regression_path.read_bytes()).hexdigest()}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
quick_path=root/'outputs'/'quick_improvements'
if (quick_path/'independent_audit.json').exists():
    audit=json.loads((quick_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful']
    comparisons={}
    for kind in ('valve','physics'):
        result_path=quick_path/f'{kind}_results.json'
        result=json.loads(result_path.read_text(encoding='utf-8'))
        assert audit['evaluations'][kind]['results_sha256']==hashlib.sha256(result_path.read_bytes()).hexdigest()
        if result['version']==__version__:
            for name,h in result['source_sha256'].items():
                assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
        comparisons[kind]={'version':result['version'],'results_sha256':audit['evaluations'][kind]['results_sha256'],
            'evidence_type':'plant_measured_reused_holdout' if kind=='valve' else 'simulation_only'}
    manifest['quick_improvements']={'independent_audit_verified':True,'evaluations':comparisons,
        'scope':'Valve dynamics option, mixed hydraulic reference and bounded mass-balance error. No universal performance improvement claim.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
remaining_path=root/'outputs'/'remaining_modules'
if (remaining_path/'independent_audit.json').exists():
    audit=json.loads((remaining_path/'independent_audit.json').read_text(encoding='utf-8'))
    result=json.loads((remaining_path/'results.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((remaining_path/'results.json').read_bytes()).hexdigest()
    assert audit['chiller_attribution_sha256']==hashlib.sha256((remaining_path/'chiller_attribution.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    manifest['remaining_modules']={'version':result['version'],'evidence_type':result['evidence_type'],
        'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'chiller_attribution_sha256':audit['chiller_attribution_sha256'],
        'scope':'Rank 4/5/7/8/9 optional engineering models and simulated comparisons; rank 6 score attribution only; boiler observer not implemented.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
measured_path=root/'outputs'/'acquired_modules_validation'
if (measured_path/'independent_audit.json').exists():
    result=json.loads((measured_path/'results.json').read_text(encoding='utf-8'))
    audit=json.loads((measured_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful']
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    assert audit['results_sha256']==hashlib.sha256((measured_path/'results.json').read_bytes()).hexdigest()
    manifest['acquired_measured_evaluation']={
        'version':result['version'],'results_sha256':audit['results_sha256'],
        'independent_audit_verified':True,
        'modules':{k:{'status':v['status'],'comparison':v['comparison']} for k,v in result['modules'].items()},
        'scope':'Filter future service-limit risk proxy; induced-fault heat pump on one prototype; RO lacks fault truth and fails strict training pressure quality. Unqualified RO approximation separate.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
improvement_path=root/'outputs'/'filter_heatpump_improvement'
if (improvement_path/'independent_audit.json').exists():
    result=json.loads((improvement_path/'results.json').read_text(encoding='utf-8'))
    audit=json.loads((improvement_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((improvement_path/'results.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    manifest['filter_heatpump_improvement']={
        'version':result['version'],'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'filter':{k:v['comparison'] for k,v in result['filter']['evaluations'].items()},
        'heatpump_reused':result['heatpump']['comparison'],
        'scope':'Filter reused Test and unused suffixes on known specimens separate; no new independent heat-pump EF qualification. Filter false-positive reduction trades off recall.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
operating_path=root/'outputs'/'filter_heatpump_operating_points'
if (operating_path/'independent_audit.json').exists():
    result=json.loads((operating_path/'results.json').read_text(encoding='utf-8'))
    audit=json.loads((operating_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((operating_path/'results.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    manifest['filter_heatpump_operating_points']={
        'version':result['version'],'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'filter':{k:v['comparison'] for k,v in result['filter']['evaluations'].items()},
        'heatpump_reused':result['heatpump']['comparison'],
        'earlier_attempts':audit['earlier_attempts'],
        'scope':'All evaluations reused, including former unused suffix. Four development settings retained. Filter improvement requires observed dust feed and material. No new independent measured-data qualification.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
followup_path=root/'outputs'/'diagnostic_followup'
if (followup_path/'independent_audit.json').exists():
    result=json.loads((followup_path/'results.json').read_text(encoding='utf-8'))
    audit=json.loads((followup_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((followup_path/'results.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    new=json.loads((root/'outputs/diagnostic_gap_analysis/new_independent_physical_validation.json').read_text(encoding='utf-8'))
    manifest['diagnostic_followup']={
        'version':result['version'],'results_sha256':audit['results_sha256'],'independent_audit_verified':True,
        'heatpump_reused':result['heatpump']['comparison'],
        'filter_reused':{k:v['comparison'] for k,v in result['filter']['evaluations'].items()},
        'filter_decisions_unchanged':audit['filter_decisions_unchanged'],
        'temporal_evidence_replayed_rows':audit['ewma_cusum_independently_replayed_rows'],
        'new_independent_physical_indicator_rows':new['rows'],'new_data_fault_accuracy':None,
        'new_ro_observations_same_apparatus':audit['new_ro_observations_same_apparatus'],
        'scope':'Sequential1..4 analysis, normal-calibrated EWMA/CUSUM and filter uncertainty annotations. Measured fault performance reused. New charge-sweep data validate physical identities only. New RO experiments fail pressure-order QC.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
stage56_path=root/'outputs/stage56_ensemble'
if __version__ in ('0.13.0','0.14.0','0.15.0','0.16.0'):
    result=json.loads((stage56_path/'results.json').read_text(encoding='utf-8'))
    audit=json.loads((stage56_path/'independent_audit.json').read_text(encoding='utf-8'))
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((stage56_path/'results.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in result['source_sha256'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    else:
        with zipfile.ZipFile(stage56_path/'evaluated_source_snapshot.zip') as z:
            for name,h in result['source_sha256'].items():assert hashlib.sha256(z.read(name.replace('\\','/'))).hexdigest()==h,name
    manifest['stage56_improvement']={'version':result['version'],'results_sha256':audit['results_sha256'],'independent_audit_verified':True,
        'heatpump':result['heatpump']['comparison'],'filter_candidates':{k:v['comparison'] for k,v in result['filter']['evaluations'].items()},
        'adoption':result['adoption'],'scope':'All fault performance reused. Training-only grouped model selection, covariance/CUSUM path adopted for development; filter default kept. No new independent fault qualification.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
if __version__=='0.14.0':
    folder=root/'outputs/completion_7_13'
    audit=json.loads((folder/'independent_audit.json').read_bytes())
    assert audit['successful']
    for name,h in audit['source_sha256'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    for name,item in audit['evaluations'].items():assert hashlib.sha256((folder/name/'results.json').read_bytes()).hexdigest()==item['results_sha256'],name
    manifest['completion_7_13']={
        'independent_audit_verified':True,'audit_sha256':hashlib.sha256((folder/'independent_audit.json').read_bytes()).hexdigest(),
        'evaluations':audit['evaluations'],
        'scope':'Tank calibration/clock audit; chiller candidate not adopted; new marine filter pressure benchmark; weak wet-coil trial; vaporizer constant-property predictor and configured boiler inventory simulation. Steam/column actual hydraulic qualification unavailable.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
if __version__ in ('0.15.0','0.16.0'):
    folder=root/'outputs/literature_improvement'
    audit=json.loads((folder/'independent_audit.json').read_bytes());result=json.loads((folder/'results.json').read_bytes())
    assert audit['successful'] and audit['results_sha256']==hashlib.sha256((folder/'results.json').read_bytes()).hexdigest()
    assert audit['decision_sha256']==hashlib.sha256((folder/'adoption.json').read_bytes()).hexdigest()
    if result['version']==__version__:
        for name,h in audit['source_sha256'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    else:
        with zipfile.ZipFile(folder/'evaluated_source_snapshot.zip') as z:
            for name,h in audit['source_sha256'].items():assert hashlib.sha256(z.read(name.replace('\\','/'))).hexdigest()==h,name
    manifest['literature_improvement']={
        'version':result['version'],'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'replayed_rows':audit['independent_signed_ar1_cusum_replayed_rows'],
        'adoption':json.loads((folder/'adoption.json').read_bytes()),
        'heatpump_reused':result['heatpump']['comparison'],
        'marine_filter_reused':result['marine']['comparison'],
        'new_independent_fault_metrics':None,
        'scope':'Literature-informed signed/blocked/AR1/physical-proxy candidates. HP signed-block profile selected for development; weak EF10.1 unchanged. Every filter candidate rejected for high false alarms. No new independent qualification.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
if __version__=='0.16.0':
    folder=root/'outputs/two_target_improvement';audit=json.loads((folder/'independent_audit.json').read_bytes())
    assert audit['successful']
    assert audit['results_sha256']==hashlib.sha256((folder/'results.json').read_bytes()).hexdigest()
    assert audit['assessment_sha256']==hashlib.sha256((folder/'assessment.json').read_bytes()).hexdigest()
    assert audit['adoption_sha256']==hashlib.sha256((folder/'adoption.json').read_bytes()).hexdigest()
    for name,h in audit['source_sha256'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,name
    manifest['two_target_improvement']={
        'version':__version__,'independent_audit_verified':True,'results_sha256':audit['results_sha256'],
        'assessment_sha256':audit['assessment_sha256'],'replayed_rows':audit['independent_prediction_replayed_rows'],
        'adoption':json.loads((folder/'adoption.json').read_bytes()),
        'new_independent_fault_metrics':None,
        'scope':'Filter context/normal-augmentation/growth trials rejected for FPR. HP weak measured-cohort discrimination improved via condensing-temperature response with session/bias confounding unresolved. Raw detections and off-delay occupancy separated. JSON matrix order explicitly preserved.'}
    (evidence/'release.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest, indent=2))
