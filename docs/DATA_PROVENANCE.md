# External data register

No raw measurements, workbook extracts, publisher source code, papers or fitted corpus
profiles are included in the public software. This register is an acquisition/reuse map.
The downloader scripts contain exact file URLs and checksums where recorded; publisher
availability and terms must be rechecked before a new download. A data link is not a
claim of fault-detection validation.

| Corpus / source | Local acquisition location (not shipped) | Measurements / labels | Applied scope / reason blocked |
| --- | --- | --- | --- |
| [DAMADICS](http://diag.mchtr.pw.edu.pl/damadics/) Lublin factory | `research_support/public_data/damadics/` | Actuator command/position, documented injected faults, background days | Valve tracking; new background and reused faults are distinct |
| [RP-1043 redistribution](https://doi.org/10.6084/m9.figshare.28435232) | `public_data/chiller/rp1043.zip` under research_support | Water/refrigerant/oil measurements and experiment fault labels | Chiller; single apparatus, poor transfer of additional residual paths |
| [Distillation 17628963](https://zenodo.org/records/17628963) | `public_data/column/data.zip` | 28 process experiments | Internal vapor/liquid flows and qualified flooding truth missing |
| [HSE filter, Kaggle](https://www.kaggle.com/datasets/prognosticshse/preventive-to-predicitve-maintenance) v8 | `public_data/acquisition_20261105/filter_hse/filter.zip` | DP, unqualified absolute flow unit used as ratio, trial time, dust conditions; provider600Pa service endpoint | Risk of reaching service limit within30s, not current blockage truth; original Train/Test remain separate |
| [NREL dynamic RO 649](https://mhkdr.openei.org/submissions/649) | `public_data/acquisition_20261105/ro_nrel/` | Pressures, flows, dynamic inputs; no qualified fouling truth | Feed/concentrate pressure ordering fails; actual diagnosis not scored |
| [Wet/frosting coil](https://data.mendeley.com/datasets/s6d23g2m2w/1) | `public_data/acquisition_20261105/coil_frost/` | DP, air quantities, temperatures/humidity, controlled fouling, all runs with frost | Air-side calculation; weak foul detection, CC BY-NC3.0 source excluded |
| [3-tank laboratory](https://github.com/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data) commit57557ea940bdc379fc0a5052a04c91ce1c9f86cd | `public_data/acquisition_20261105/tank_three/repository.zip` | Voltage sensors, creator calibration, fault scenarios | Level calibration only; no qualified leak mass/flow/shape/time combination; no explicit repository licence found at acquisition |
| [Propane heat pump 5155136](https://zenodo.org/records/5155136) | `public_data/acquisition_20261105/heatpump_propane/` | Refrigerant measurements, demand, fault code/intensity; separate superheat logger | Single prototype. Main10s and aux5s clocks need causal matching, never label/intensity matching |
| [Independent R290 receiver22097811](https://zenodo.org/records/22097811) | `public_data/gap_analysis_20261105/r290_receiver/` | 195 operating points, charge experiments | New apparatus only for physical calculation checks; no compatible EF fault/normal split |
| RO measured WEC response | `public_data/gap_analysis_20261105/ro/wec_sim.zip` | Measured RO response driven by simulated wave-energy input | Actual response is measured; input source is simulated.36398rows still fail pressure ordering |
| [Marine engine19857425](https://zenodo.org/records/19857425) | `public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip` | One Matsui engine, 16CSV, reference and injected fault files,69sensor quantities, AnomalyState | Independent engine corpus at0.14; subsequent0.15/0.16 evaluations reused. No measured compressor air flow. Publisher CC BY4.0 |
| [Capillary leak20582921](https://zenodo.org/records/20582921) | `public_data/completion_20261106/20582921/` | Gas T/P profiles,5×2conditions | No qualified healthy reference, absolute pressure/volume model insufficient for tank balance |
| [Extruder21987832](https://zenodo.org/records/21987832) | `public_data/completion_20261106/21987832/` | 60runs, temperature/current/voltage | No DP/flow; referenced labels absent in publisher list. Optional101MB current archive not downloaded |

Paths abbreviated after the first rows are relative to `research_support/`. Directory
names are historical acquisition batches, not unique apparatus counts.

## Acquisition and audit entry points

- `scripts/validate_public_data.py --download`: initial RP-1043/DAMADICS/column acquisition and benchmark.
- `scripts/acquire_actual_datasets.py --download`: HSE/RO/coil/tank/heat-pump originals.
- `scripts/inspect_acquired_actual_data.py`, `scripts/audit_acquired_actual_data.py`: inventory and independent archive checks.
- `scripts/acquire_followup_data.py`: follow-up receiver/RO download metadata and hashes.
- `scripts/acquire_completion_data.py`: later Zenodo records, publisher MD5 plus local SHA256.
- `scripts/inspect_completion_scope.py`: sensor/label suitability of later corpora.

`evidence/artifact_index.json` hashes the preserved local research artefacts; only
explicitly curated aggregate records and our original code snapshot are public.
Do not expect a public checkout to contain the excluded inputs those scripts reference.
MATLAB MCOS parsing is pinned to the recorded HSE layout and uses a private SciPy
reader interface; it is not a general MAT parser. A changed provider artifact must fail
qualification rather than be silently accepted.

Licences were recorded at acquisition. The earlier acquisition notes identify filter,
RO and propane heat-pump datasets as CC BY4.0, coil as CC BY-NC3.0, and no explicit tank
repository licence. No blanket permission is inferred from public accessibility.
See [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md).
