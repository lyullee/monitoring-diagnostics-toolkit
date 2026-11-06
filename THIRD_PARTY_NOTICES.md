# Provenance, attribution and redistribution boundaries

The MIT licence covers the original toolkit implementation and its original documentation.
It does not relicense referenced publications, external repositories, measured datasets,
standards, vendor manuals or optional Python dependencies. Standard licence wording,
scientific names, identifiers, equations and attribution are intentionally retained.
Changing wording is not a substitute for permission or attribution.

The shipped equipment calculations are original screening implementations of physical
balances and statistical ideas. They are not claimed to reproduce an entire cited paper,
commercial monitor, proprietary standard, or a vendor's internal fault classifier.
The implementation-to-literature table in [IMPLEMENTATION](docs/IMPLEMENTATION.md),
[model guide](docs/MODEL_GUIDE.md) and stage-specific research records describe the actual scope.

## Excluded materials

The public repository, wheel and source distribution exclude `.upstream/`, `.venv/`,
`research_support/`, raw measured archives, extracted observations, downloaded papers,
fitted dataset-specific models and row-level benchmark predictions. Acquire external
materials separately from their publishers and comply with the terms at acquisition.
Aggregate results in the research notes are reported observations, not redistributed corpora.

| External material | Attribution / access | Public release treatment |
| --- | --- | --- |
| Marine engine experiment | [Zenodo 19857425](https://zenodo.org/records/19857425), publisher CC BY 4.0 metadata | Original archive and derived row files excluded; source and experiment acknowledged |
| Propane heat-pump fault experiment | [Zenodo 5155136](https://zenodo.org/records/5155136); Bellanco et al., [2022 paper](https://doi.org/10.1016/j.ijrefrig.2021.10.017) | Workbook and fitted profiles excluded; original publication governs reuse |
| Wet/frosting coil experiment | [Mendeley Data s6d23g2m2w v1](https://data.mendeley.com/datasets/s6d23g2m2w/1), CC BY-NC 3.0 in acquisition record | Noncommercial dataset not included in MIT software |
| HSE filter service-life corpus | [Kaggle source](https://www.kaggle.com/datasets/prognosticshse/preventive-to-predicitve-maintenance) | No raw MAT/CSV or trained tree bundles distributed; verify provider terms separately |
| DAMADICS industrial valves | DAMADICS benchmark, Lublin sugar-factory recordings | Downloads and extracted records excluded; acquisition code and research attribution retained |
| ASHRAE RP-1043 chiller data | [Redistribution record](https://doi.org/10.6084/m9.figshare.28435232) and original RP-1043 project | Raw records excluded; repository availability does not establish unrestricted rights |
| Dynamic reverse osmosis | [NREL/MHKDR 649](https://mhkdr.openei.org/submissions/649) | Archives and measured response files excluded |
| Liquid-level laboratory data | [Creator repository](https://github.com/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data); [paper](https://doi.org/10.1002/adc2.70011) | Creator code, MLX, workbooks and extracted rows excluded; calibration provenance cited |
| Distillation, receiver, leak and extruder datasets | See [data register](docs/DATA_PROVENANCE.md) | Downloaded files excluded, including datasets unsuitable for these APIs |
| Related lyullee projects | [Pinned revisions](docs/UPSTREAM_REVISIONS.json) | Only original interface adapters shipped; no upstream source vendored |

## Dependencies and methods

NumPy is a runtime dependency; scikit-learn is used only by optional training paths.
Pandas, SciPy, openpyxl, xlrd, CoolProp, fluids and ht are optional research/verification
dependencies. They are installed separately under their own licences, not copied into this
distribution. Inspect each dependency's actual installed licence before redistributing it.
Exporting fitted tree arrays is a toolkit inference format, not a claim of inventing
ExtraTrees, gradient boosting or random forests. No pretrained dataset model is included.

NIST CUSUM/EWMA, regression, covariance residuals, fixed-length block calibration,
and time-delay alarm ideas are identified by name in the model and literature guides.
This implementation does not claim stationary-bootstrap or AR-sieve algorithm equivalence.
No purchased standard or vendor manual text is included.

The release review checks distribution membership, credentials/path patterns and explicit
source attribution. It is not a legal opinion or proof that every possible third-party claim
has been eliminated. Report a specific provenance concern through the repository issues.
