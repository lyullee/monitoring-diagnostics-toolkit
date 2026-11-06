# Documentation map

## Current public documentation

- [README](../README.md): module purposes, sensors/units, parameters, outputs, examples and current evidence.
- [USER_GUIDE](USER_GUIDE.md): Python/CSV/JSON workflow, normal references, calibration, results and streaming.
- [API_REFERENCE](API_REFERENCE.md) / [API_CATALOG.json](API_CATALOG.json): public callable signatures, defaults, role declarations and source definitions.
- [MODEL_GUIDE](MODEL_GUIDE.md): equations, assumptions, output meaning, method references and omitted parts.
- [DEVELOPMENT_HISTORY](DEVELOPMENT_HISTORY.md): retrospective milestones, decisions and failures.
- [DATA_PROVENANCE](DATA_PROVENANCE.md): corpus sources, sensors, truth, incompatibilities and acquisition scripts.
- [REPRODUCIBILITY](REPRODUCIBILITY.md): clean software checks, historical pipelines, frozen splits and source-hash constraints.
- [RESEARCH_HANDOFF](RESEARCH_HANDOFF.md): selected/rejected profiles, open questions and next evidence required.
- [RELEASE](RELEASE.md): public distribution, rights boundaries and publication ledger.
- [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md), [LICENSE](../LICENSE), [CONTRIBUTING](../CONTRIBUTING.md), [CITATION](../CITATION.cff).

## Historical research documents

These are original stage records, preserved rather than silently rewritten as if their
results had been known earlier. Statements about missing functions describe that stage.
For current availability use README/API_REFERENCE; for newer measured caveats use the
latest two-target record. Paths under outputs/research_support in old documents refer
to excluded local research materials, not promised contents of a public checkout.

| Topic | Record |
| --- | --- |
| Original scope / research-to-code correspondence | [IMPLEMENTATION](IMPLEMENTATION.md), [CAPABILITIES](CAPABILITIES.md) |
| Physics / six verification classes | [PHYSICS_VALIDATION](PHYSICS_VALIDATION.md), [SIX_STAGE_VERIFICATION](SIX_STAGE_VERIFICATION.md) |
| First measured data | [PUBLIC_DATA_VALIDATION](PUBLIC_DATA_VALIDATION.md) |
| Chiller progression | [CHILLER_UPGRADE](CHILLER_UPGRADE.md), [CHILLER_STAGES](CHILLER_STAGES.md) |
| Early physical upgrades | [QUICK_IMPROVEMENTS](QUICK_IMPROVEMENTS.md), [REMAINING_MODULES](REMAINING_MODULES.md) |
| Valve background qualification | [VALVE_MONITOR_QUALIFICATION](VALVE_MONITOR_QUALIFICATION.md) |
| Additional data / application | [ACTUAL_DATA_ACQUISITION](ACTUAL_DATA_ACQUISITION.md), [ACQUIRED_MODULES_VALIDATION](ACQUIRED_MODULES_VALIDATION.md) |
| Filter / heat-pump improvements | [FILTER_HEATPUMP_IMPROVEMENT](FILTER_HEATPUMP_IMPROVEMENT.md), [FILTER_HEATPUMP_OPERATING_POINTS](FILTER_HEATPUMP_OPERATING_POINTS.md) |
| Sequential and covariance stages | [DIAGNOSTIC_FOLLOWUP](DIAGNOSTIC_FOLLOWUP.md), [STAGE56_IMPROVEMENT](STAGE56_IMPROVEMENT.md) |
| Remaining priority7–13 | [COMPLETION_7_13](COMPLETION_7_13.md) |
| Literature / bottleneck review | [LITERATURE_IMPROVEMENT](LITERATURE_IMPROVEMENT.md), [TWO_BOTTLENECK_REVIEW](TWO_BOTTLENECK_REVIEW.md) |
| Latest raw detection / alarm hold / confounding | [TWO_TARGET_IMPROVEMENT](TWO_TARGET_IMPROVEMENT.md) |
| Pinned integrations | [UPSTREAM_REVISIONS.json](UPSTREAM_REVISIONS.json) |
| Prior README snapshot | [DEVELOPMENT_README_ARCHIVE](DEVELOPMENT_README_ARCHIVE.md) |

Research-specific reference tables and reports under excluded research_support/outputs
are indexed by file hashes in evidence/artifact_index.json. This index supports local
recovery but does not grant permission to redistribute external corpora.
