# VKU-27 local assumption smoke test

`scripts/local_assumption_smoke.py` is a local-only, assumption-based smoke
harness for VKU-27. It is deliberately separate from `scripts/validate_local.py`
(the older no-assumption inventory harness).

## What it does

1. Builds an assumption-based reviewed mapping and writes it to
   `derived/registry/benefit-classification.json` (backing up the prior file to
   `benefit-classification.prior.json`). The mapping is deterministic for a
   given prepared terms version.
2. Re-runs preparation so `preparation._prepare_rules` re-ingests every clause
   against the new mapping fingerprint.
3. Evaluates the active rules against the local SQLite ledger with only recorded
   assumptions (assumed enrollment/portal state; no merchant-group table).
4. Runs one end-to-end status/value/deadline/citation question through the
   deterministic ReAct loop (`react.ScriptedModel`) using an offline
   metadata-filter citation retriever over the official-clause index.
5. Runs the multi-benefit planner over the same verified facts.

All outputs are written under `PERKWATCH_DATA_DIR/prepared/evaluation/`:

- `vku-27-local-assumption-smoke-report.json`
- `vku-27-local-assumption-smoke-manifest.json`
- `vku-27-assumptions.json`

## Assumptions (recorded, not verified)

- Every mapped benefit is treated as available; the latest staged guide is
  treated as current.
- Dollar-capped Amex benefits are `supported` with period amounts/types derived
  from guide slugs/text (see `vku-27-assumptions.json`).
- Non-dollar Amex benefits are `known_untrackable` with a named
  `missing_data_source`.
- The Chase guide is unstructured and stays `indeterminate` (one `chunk` slug).
- Benefits marked `enrollment_required` are assumed enrolled; no portal/login
  verification was performed.
- No merchant resolution exists (all local merchant decisions are
  `indeterminate`), so every supported benefit with an in-period transaction
  evaluates to `indeterminate` (`unresolved_merchant`).

## Honest limitations

No concrete account accuracy is claimed. Status/value/deadline results are
indeterminate because merchant resolution is absent. Accuracy, false-unused,
precision, and recall are `null` in the report (no human-labelled local cases).

## Validators

`evals/scripts/validate_slice17.py` compares the number of distinct active
benefits against the mapping's `supported` tally; it was adjusted to deduplicate
per-clause active rules by `benefit_id` so a multi-clause supported benefit is
counted once.
