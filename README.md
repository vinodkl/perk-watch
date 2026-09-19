# PerkWatch Slice 0 (VKU-12)

Frozen, offline-only inputs for the PerkWatch evaluation. Everything in `data/` is synthetic except the schema shape and source metadata fields. No real benefit guides, statements, or full Reddit threads are included.

## Contents

- `data/terms/`: 10-benefit registry and clause-level synthetic corpus, versioned by `terms_version`.
- `data/community/served_ideas.json`: ideas eligible for serving.
- `data/community/conflicting_ideas.json`: seeded known-bad ideas retained only for the authority-boundary safety case.
- `data/fixtures/transactions.csv`: clearly synthetic ledger rows.
- `data/eval/frozen_cases.json`: 36 human-authored expected outcomes.
- `scripts/validate_slice0.py`: reproducibility and acceptance checks, including exact conflict accuracy.

Run:

```sh
python3 scripts/validate_slice0.py
```

The validator prints dataset version, category counts, exact numerators/denominators, observed failures, and known coverage gaps. It does not fetch the network.

## Deliberate follow-ups

1. Re-verify the 10-benefit list and matching against the logged-in account view before submission.
2. At implementation start, expand matching to all benefits across both cards. Non-observable benefits still need a new data source and remain deferred.

## Provenance boundary

The fixture records use `synthetic: true` and `example.invalid` URLs. Replace neither with copied guide text, personal statements, nor full Reddit threads. A future offline collector may store source IDs, URLs, dates, short excerpts, derived ideas, and review metadata only.
