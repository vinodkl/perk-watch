# PerkWatch

## Slice 0.5 (VKU-22), local real-data staging

Manual public benefit guides and local CSV/OFX exports can be staged outside the repository. Set `PERKWATCH_DATA_DIR` or use the default `~/.local/share/perk-watch`; see [docs/local-data-staging.md](docs/local-data-staging.md). No login, account API, live lookup, or credential storage is used.

```sh
python3 scripts/check_local_data_guard.py
```

## Slice 1 (VKU-15), transaction ingest and merchant resolution

`TransactionSource` reads CSV and OFX exports into a normalized ledger: transaction and posted dates, raw descriptor, integer minor-unit amount, card, and MCC. OFX imports require a supplied card because OFX does not standardize it; each record must still provide its MCC or use the supplied fallback.

`resolve_merchants(transactions, resolve_descriptor)` accepts canonical merchant facts only from the supplied model resolver. A resolver returning `None` creates an explicit `indeterminate` result, never a guessed merchant. `data/frozen/eval/merchant_cases.json` contains 24 synthetic human-authored labels and `scripts/validate_slice1.py` reports precision/recall and reproducibility.

Run:

```sh
PYTHONPATH=src python3 scripts/validate_slice1.py
```

## Slice 0 (VKU-12), frozen inputs

Frozen, offline-only inputs for the PerkWatch evaluation. Everything in `data/` is synthetic except the schema shape and source metadata fields. No real benefit guides, statements, or full Reddit threads are included.

## Contents

- `data/frozen/terms/`: 10-benefit registry and clause-level synthetic corpus, versioned by `terms_version`.
- `data/frozen/community/served_ideas.json`: ideas eligible for serving.
- `data/frozen/community/conflicting_ideas.json`: seeded known-bad ideas retained only for the authority-boundary safety case.
- `data/frozen/fixtures/transactions.csv`: clearly synthetic ledger rows.
- `data/frozen/eval/frozen_cases.json`: 36 human-authored expected outcomes.
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
