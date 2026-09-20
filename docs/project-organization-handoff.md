# PerkWatch project-organization handoff

## Local data model

Real data is local-only under `PERKWATCH_DATA_DIR`:

```text
raw/<card>/
  benefits/                     manually collected issuer guides
  transactions/                 manually exported CSV/OFX files
  community/<collection>/       sanitized Reddit metadata and reviewed ideas
  sources.json                  hashes and source provenance
prepared/
  benefits/current.json         current versioned clause corpus
  benefits/<terms-version>/     immutable clause version
  transactions/ledger.sqlite3   normalized, deduplicated transactions
  community/<card>/             current reviewed community data
  report.json                   changes and invalidations from the last run
```

Raw and prepared real data are gitignored. Tracked synthetic evaluation data
lives only under `evals/data/frozen/`.

## Operator workflow

1. Run the local-card collection skill for each card to add benefit guides and transactions.
2. Run the community collection skill for each card to add sanitized public notes.
3. Prepare all cards offline:

   ```sh
   PYTHONPATH=src PERKWATCH_DATA_DIR=data/real python3 scripts/prepare_data.py
   ```

4. Before committing, run:

   ```sh
   python3 scripts/check_local_data_guard.py
   ```

Preparation is idempotent. It hashes benefit sources, assigns a deterministic
terms version, reports clause changes and invalidations, normalizes supported
issuer CSV/OFX exports, deduplicates transactions, and rebuilds reviewed
community output. Community reviews tied to old terms are rejected.

## Repository organization

- `src/perk_watch/raw_data.py`: card-centered raw imports and provenance.
- `src/perk_watch/preparation.py`: one preparation coordinator.
- `src/perk_watch/benefit_preparation.py`: clause extraction, terms versions, diffs, invalidations.
- `src/perk_watch/transactions.py`: CSV/OFX normalization and SQLite ledger.
- `src/perk_watch/community.py`: community deduplication and current-terms review filtering.
- `scripts/prepare_data.py`: operator entry point.
- `scripts/check_local_data_guard.py`: prevents local/private artifacts from entering Git.
- `evals/`: all tracked synthetic fixtures and validation scripts.

## Boundaries and remaining work

Preparation never logs in or fetches issuer/Reddit data. Login, MFA, downloads,
and public-community collection remain explicit skill/user actions. The current
benefit preparation produces clause chunks and invalidation reports; VKU-17
still owns Extractor/Verifier rule generation. VKU-13 still owns the official
RAG index, and the ReAct runtime remains later work.

Documentation should use **raw data**, **prepared data**, **card**, **benefit**,
**community idea**, and **terms version** consistently; see `CONTEXT.md`.
