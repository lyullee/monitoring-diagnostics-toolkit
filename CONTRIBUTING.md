# Contributing

Start with README, docs/MODEL_GUIDE.md and docs/RESEARCH_HANDOFF.md. Keep role names,
units, clock, asset, origin, validity, episode and measurement basis explicit. Optional
dependencies must remain optional at core import time. Do not deserialize untrusted pickle.

For each meaningful numerical change, select applicable checks from these six classes:

1. Invalid inputs: missing/wrong units, incompatible identities, nonphysical values.
2. Hand-checkable calculations: independent expected numbers, not a duplicate implementation.
3. Extremes: zero/limiting values, overflow/underflow, clock resolution, boundaries.
4. Connections: units/identity/basis survive result-to-next-model and JSON restoration.
5. Regression: rerun affected existing tests; report warnings, missing optional engines and skips.
6. Complete execution: input to final output with installed-package or CLI smoke checks.

Report empirical changes with frozen train/calibration/evaluation manifests and confusion
counts, decision coverage, event detection and delay. Clearly label reused evaluation,
fresh observations on the same apparatus, new independent apparatus, and simulation.
An independent recount is not an independent test dataset. Record rejected candidates.

Never commit raw datasets, papers, private checkouts, credentials, fitted corpus models,
environment directories or absolute personal paths. Preserve scientific attribution and
licence notices. Do not replace copied code with superficially renamed variables and call
it original. Discuss a concrete provenance concern before including external implementation.

Run `python scripts/prepare_public_documentation.py` after API changes and inspect its
diff. It extracts signatures; it does not replace human explanation of dynamic roles.
Use `python scripts/release_audit.py` on actual built distributions before publishing.
