# V2 Phase 1 local-data design

## Stable identities

The only supported cards are `amex_platinum` and `chase_sapphire_preferred`.
Their raw directories use hyphenated slugs. Benefit IDs are `<card_id>_...`.
Transaction IDs are SHA-256 hashes of card, posted date, cleaned description,
minor-unit amount, and currency, so overlapping CSV/OFX exports collapse.

## Local files

Inputs are `PERKWATCH_DATA_DIR/raw/<card>/`, with `sources.json`, `benefits/`,
`transactions/`, and optional `community/`. Outputs are
`PERKWATCH_DATA_DIR/prepared/perkwatch.sqlite` and `report.json`. No command
writes outside the configured data root.

## SQLite

`cards` and `sources` anchor every row. `benefits` stores extracted terms and
minor-unit amounts, `transactions` stores exact ledger facts,
`merchant_matches` stores an exact/model/unknown decision, and `credit_matches`
stores unambiguous issuer statement-credit evidence. `community_ideas` stores
only current, conflict-free ideas. Every prepared benefit and transaction
points to a source row.

## Benefit extraction

Structured JSON guides are always accepted locally so stable IDs and canonical
terms remain unchanged. For unstructured input, the optional OpenAI adapter
requests JSON and uses `null` for unclear fields. The validator requires a title
and supporting terms, checks IDs and typed values, and skips malformed records.
Without `OPENAI_API_KEY`, plain text becomes title-plus-terms with unknown
structured fields. This makes synthetic tests and offline dry runs repeatable
without a network call.

## Monthly work

Source files are content-addressed before preparation. Each run re-reads local
sources, replaces rows by stable IDs, deduplicates transactions, re-matches
merchants, validates community terms versions, and rewrites the report. Search
indexes are intentionally deferred to Phase 2/4.

## Privacy boundary

Issuer login, MFA, CAPTCHA, account selection, and exports are manual. The
structured extractor receives benefit text only. When `OPENAI_API_KEY` is set,
unknown merchant descriptions are deduplicated, stripped of digit-bearing
tokens, and sent in batches with the fixed merchant list. No transaction rows,
amounts, dates, filenames, or account data are sent. Exact and explicit-credit
matching remain local.
