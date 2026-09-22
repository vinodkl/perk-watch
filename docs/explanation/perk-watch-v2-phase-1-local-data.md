# PerkWatch V2 Phase 1: Monthly update and local data

Build the local data setup that every later phase reads. See [PerkWatch V2 design](perk-watch-v2-design.md).

**Status:** Complete

## Goal

A user can collect current information for both cards, run one preparation command, and get clean local data without committing private files to git.

## Design first

Before implementation, decide and record:

- The SQLite tables for cards, benefits, transactions, merchant matches, and source references.
- The files stored under `raw/` and `prepared/`.
- Stable card and benefit IDs.
- The JSON format produced when an LLM reads benefit text.
- How missing or unclear benefit fields are stored as `unknown`.
- How repeated transaction exports are recognized and deduplicated.
- Which preparation steps run every month and which run only when source files change.

Keep the design specific to two cards. Do not build a general card platform.

## Work

- [x] Create the Phase 1 modules under `v2/src/perk_watch/prepare/`.
- [x] Read collected Amex Platinum and Chase Sapphire Preferred files from `PERKWATCH_DATA_DIR`.
- [x] Use an LLM to convert benefit text into validated JSON with source references.
- [x] Import CSV and OFX transactions into SQLite using integer minor units.
- [x] Deduplicate overlapping transaction exports.
- [x] Match cleaned merchant descriptions to a fixed merchant list and store `unknown` when the model is unsure.
- [x] Validate saved community checks and keep only ideas marked `no_known_conflict` for the current benefit information.
- [x] Write a preparation report with counts, skipped records, and unresolved fields.
- [x] Keep `v2/scripts/prepare_data.py` small and assemble the preparation modules from it.
- [x] Run `v2/scripts/check_local_data_guard.py` after preparation.

## Privacy rules

- Real benefits, transactions, community notes, databases, and generated files stay under `PERKWATCH_DATA_DIR`.
- Issuer login, multifactor authentication, account selection, and transaction export remain manual.
- Reddit collection uses public pages without logging in and stores no usernames or full discussions.
- Merchant matching may send only a cleaned merchant description and fixed merchant list to the LLM. Amounts, dates, account details, filenames, and full transaction rows stay local.

## Done when

- One preparation command processes both cards without contacting issuers or Reddit.
- Running preparation again with overlapping exports does not duplicate transactions.
- Every prepared benefit and transaction has a stable card ID and source reference.
- Invalid LLM output is rejected, while unclear supported fields are saved as `unknown`.
- The preparation report lists processed, skipped, and unresolved records.
- The local-data safety check passes.

## Checks

```sh
python3 v2/scripts/check_local_data_guard.py
python3 -m unittest discover -s v2/tests
```

Add focused V2 tests for repeated imports, invalid LLM output, unknown fields, and transaction deduplication.

## Completion evidence

- A clean rebuild prepared 63 benefits, 1,362 deduplicated transactions, 63 current community ideas, and 13 explicit statement-credit matches.
- Repeated preparation produced identical primary-ID sets and counts.
- All prepared benefits and transactions passed source, card-ID, and foreign-key integrity checks.
- The 11 focused V2 tests and local-data guard pass.

## Depends on

Nothing. This is the first V2 phase.
