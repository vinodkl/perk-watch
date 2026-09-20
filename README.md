# PerkWatch

## Local data

Skills manually collect three raw inputs for each card: issuer benefit guides,
transaction exports, and sanitized public-community notes. They live under
`PERKWATCH_DATA_DIR/raw/<card>/`; real data is never committed.

One offline command converts all raw inputs into the linked local model under
`PERKWATCH_DATA_DIR/prepared/`:

```sh
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real python3 scripts/prepare_data.py
```

The command hashes and versions benefit terms, normalizes and deduplicates
transactions, rebuilds reviewed community snapshots, and writes one report.
See [docs/local-data.md](docs/local-data.md).

## Slice 2 (VKU-16), deterministic benefit status

`perk_watch.benefits` calculates all benefit periods, eligible transactions, remaining minor units, deadlines, and the four statuses without an LLM. Merchant resolution may supply canonical merchant facts, but it cannot calculate or override eligibility, dates, amounts, occurrence, remaining value, deadlines, or status. Missing enrollment, portal, anniversary, limit, or potentially eligible transaction evidence returns `indeterminate` with reason and evidence IDs.

```sh
PYTHONPATH=src python3 evals/scripts/validate_slice2.py
```

## Local-data safety

No preparation command logs in, fetches issuer pages, or contacts Reddit.
Collection remains an explicit manual/skill action. Check that local artifacts
are not tracked with:

```sh
python3 scripts/check_local_data_guard.py
```

## Slice 1 (VKU-15), transaction ingest and merchant resolution

`TransactionSource` reads CSV and OFX exports into a normalized ledger: transaction and posted dates, raw descriptor, integer minor-unit amount, card, and MCC. OFX imports require a supplied card because OFX does not standardize it; each record must still provide its MCC or use the supplied fallback.

`resolve_merchants(transactions, resolve_descriptor)` accepts canonical merchant facts only from the supplied model resolver. A resolver returning `None` creates an explicit `indeterminate` result, never a guessed merchant. `evals/data/frozen/eval/merchant_cases.json` contains 24 synthetic human-authored labels and `evals/scripts/validate_slice1.py` reports precision/recall and reproducibility.

Run:

```sh
PYTHONPATH=src python3 evals/scripts/validate_slice1.py
```

## Slice 0 (VKU-12), frozen inputs

Frozen, offline-only inputs for the PerkWatch evaluation live under `evals/data/frozen/`. Terms, community safety cases, and transaction fixtures are synthetic. Public Reddit provenance and local collection inputs remain under each card's `PERKWATCH_DATA_DIR/raw/<card>/community/` directory.

## Contents

- `evals/data/frozen/terms/`: 10-benefit registry and clause-level synthetic corpus, versioned by `terms_version`.
- `evals/data/frozen/community/served_ideas.json`: ideas eligible for serving.
- `evals/data/frozen/community/conflicting_ideas.json`: seeded known-bad ideas retained only for the authority-boundary safety case.
- `evals/data/frozen/fixtures/transactions.csv`: clearly synthetic ledger rows.
- `evals/data/frozen/eval/frozen_cases.json`: 36 human-authored expected outcomes.
- `evals/scripts/validate_slice0.py`: reproducibility and acceptance checks, including exact conflict accuracy.

Run:

```sh
python3 evals/scripts/validate_slice0.py
```

The validator prints dataset version, category counts, exact numerators/denominators, observed failures, and known coverage gaps. It does not fetch the network.

## Deliberate follow-ups

1. Re-verify the 10-benefit list and matching against the logged-in account view before submission.
2. At implementation start, expand matching to all benefits across both cards. Non-observable benefits still need a new data source and remain deferred.

## Provenance boundary

Synthetic fixtures use `synthetic: true` and `example.invalid` URLs. Do not replace them with copied guide text, personal statements, or full Reddit threads. The approved offline community collector may store only public source IDs, URLs, dates, short paraphrases, derived ideas, and review metadata.
