# Evidence included in the public software

`v016_evaluated_source_snapshot.zip` contains our original evaluated Python code and
hash manifest. It is an archival research snapshot, not the package to install.
`v016_protocol.json`, `v016_independent_audit.json`, `v016_adoption.json` and
`v016_aggregate_metrics.json` preserve method/evaluation decisions and aggregated results.
The audit's results/assessment hashes point to the **excluded original full outputs**;
they do not assert that every referenced file is included in this repository.

`artifact_index.json` is a hash-only inventory of local research outputs and acquisition
metadata at release preparation. Raw corpora and fitted dataset models remain excluded.
The inventory is a preservation/recovery aid, not a download mirror or a complete
reproduction bundle. Historical source snapshots and dependencies may be needed for
earlier hash-bound audits; see docs/REPRODUCIBILITY.md.

`release_verification.json` records checks on the public-release source. It is separate
from historical measured-data evaluation. `publication.json` records verified publication
status. No unknown DOI or publication success is invented.
