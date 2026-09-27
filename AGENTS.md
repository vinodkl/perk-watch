# PerkWatch agent instructions

## Work routing

PerkWatch has one implementation (V3, the credit tracker). Keep application code under `src/perk_watch/`, command-line entry points under `scripts/`, evaluation cases and runner under `evals/`, the web UI under `web/`, and tests under `tests/`. Read `docs/explanation/perk-watch-v3-benefit-tracker.md` before starting work; the V2 phase docs are history.

## Local card data

Read `.agents/skills/local-card-data-staging/SKILL.md` before collecting or importing card data.

- Use `PERKWATCH_DATA_DIR`; the local default root is `data/real/`.
- Keep raw benefit guides, statements, CSV/OFX exports, credentials, databases, search files, and generated output out of git.
- The hand-checked credit catalog (`src/perk_watch/catalog.json`) holds only public issuer facts and credit-line patterns, and is committed.
- User login, MFA, CAPTCHA, account selection, and consent remain manual.
- Stage user-supplied files with `perk_watch.staging.raw_data` so hashes and source records are written; then run `scripts/prepare_data.py` to normalize and index them.
- Never replace tracked evaluation examples with real data.
- Chat may send a credit's terms, tips, and usage amounts and dates to the model, never transaction descriptions, account details, filenames, or complete transaction rows.

## Community collection

Community tips collection is an explicit offline action (`.agents/skills/community-corpus-collection/SKILL.md`). It never runs from the application or while answering a user question.

- Store only paraphrased tips, public URLs, source titles, dates, and benefit IDs in `PERKWATCH_DATA_DIR/raw/<card>/community/tips.json`.
- Do not commit community sources, full discussions, usernames, credentials, cookies, session files, or private/deleted content.
- Use public pages without logging in. A login wall is a blocker.
- The application reads only prepared local data and makes no web requests other than model calls for chat.

## Runtime

Runtime reads prepared card data only. It does not collect issuer data, import statements, contact Reddit, or change prepared data while answering a question. The one runtime write is user-initiated: "mark used" for manually tracked credits goes to `PERKWATCH_DATA_DIR/user/profile.json`. Chat may *propose* a mark with `propose_mark`; only the user's tap writes it. Keep transactions in SQLite and use embedding search only for benefit text and community ideas.

## Safety boundaries

Do not add automated login, credential storage, bank/card APIs, cookie extraction, or live external lookup while answering user questions. Do not commit real card data, public-community data, provider session files, or full community discussions.

## Checks

Run the checks for the implementation being changed:

```sh
python3 scripts/check_local_data_guard.py
python3 -m unittest discover -s tests
```

Run the smallest additional tests that cover the change. Do not commit unless the user explicitly asks.
