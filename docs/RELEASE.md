# Public release record: 0.17.0

Project: **Monitoring Diagnostics Toolkit**. Distribution `monitoring-diagnostics-toolkit`;
import `equipment_diagnostics`; CLI `equipment-diagnose`. The public source history starts
with this release preparation. Earlier version labels are local development milestones,
not fabricated past Git tags. This release adds packaging, original explanatory docstrings,
full module/input/output documentation, research continuity records and redistribution guards.
It does not claim a newly improved diagnostic algorithm or new independent measured result.

## Preserved and excluded

The prior README and stage reports are retained, with a current index explaining their
historical scope. The v0.16 evaluated original source snapshot and selected audit/protocol
records preserve linkage to numerical claims. A hash-only local artifact index records
excluded evidence without redistributing raw observations or trained profiles.
`research_support`, `outputs`, `.upstream`, virtual environments and credentials are excluded.

Original code/docs: MIT; referenced datasets/dependencies keep separate rights. See
THIRD_PARTY_NOTICES.md. New explanations are original summaries. Scientific names,
equations, standard licence text and attribution are intentionally not erased.

## Verification and publication ledger

Machine-readable software results, environment versions and source/archive digests are
recorded in `evidence/release_verification.json` after checks. The package audit inspects
the actual wheel and source tarball and the nested original-source snapshot. Installation
smoke checks run from a directory outside the source checkout. Functional checks do not
turn historical reused fault evaluations into new blind tests.

Publication status and final GitHub/PyPI/Zenodo identifiers are maintained in
`evidence/publication.json`. A prepared workflow is not itself successful publication.
Only verified public URLs/identifiers are reported as published. Registry/archive build
files may be copied verbatim; their SHA256 identifies the specific uploaded artefacts.

The release workflow builds/tests from a published GitHub release, then uses a project-
specific PyPI trusted publisher. It does not store a long-lived PyPI API token. The trust
registration is security-sensitive and may require user action under browser policy.
