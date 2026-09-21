# VKU-27 local real-data integration

`scripts/local_real_data_integration.py` runs the staged real local dataset
separately from the synthetic frozen benchmark. It applies the reviewed local
benefit mappings, reruns preparation, and exercises the deterministic
registry/ledger evaluator, official-clause citation retrieval, ReAct question
path, and multi-benefit planner.

## Data authority

- Staged issuer guides are authoritative terms at their recorded version and
  fetch date.
- Staged transaction exports are real local transaction evidence.
- Staged Reddit records are real public community inputs, but non-authoritative;
  they cannot change status, amount, remaining value, or deadline.
- The owner-directed demo assumptions are limited to mapped-benefit
  availability/current selection and unknown enrollment or portal account state.
  They are recorded in `vku-27-account-state-assumptions.json`.

All generated outputs remain under
`PERKWATCH_DATA_DIR/prepared/evaluation/`:

- `vku-27-local-real-data-integration-report.json`
- `vku-27-local-real-data-integration-manifest.json`
- `vku-27-account-state-assumptions.json`

The mapping and its prior backup remain under the local prepared registry
directory; guides, transactions, SQLite stores, and reports are never committed.

## Honest limitations

This is an integration result over real staged inputs, not a human-labelled
accuracy benchmark. Unresolved rule fields remain indeterminate. Missing local
merchant resolution can make transaction-backed status/value/deadline results
indeterminate, and unstructured guide clauses remain unresolved rather than
invented. Accuracy, false-unused, precision, and recall are unavailable
(`null`) because no human ground truth was collected. Synthetic benchmark
counts and this integration's counts are never blended.

## Run

```sh
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real python3 scripts/prepare_data.py
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real python3 scripts/local_real_data_integration.py
python3 scripts/check_local_data_guard.py
PYTHONPATH=src python3 evals/scripts/validate_slice17.py
PYTHONPATH=src python3 evals/scripts/validate_slice25.py
python3 evals/scripts/validate_slice0.py
```
