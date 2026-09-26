# PerkWatch agent instructions

## Work routing

PerkWatch has one implementation (V2, now primary). Keep application code under `src/perk_watch/`, command-line entry points under `scripts/`, evaluation cases and runner under `evals/`, and tests under `tests/`. Read `docs/explanation/perk-watch-v2-design.md`, then read the ticket for the active phase before starting work.

## Local card data

Read `.agents/skills/local-card-data-staging/SKILL.md` before collecting or importing card data.

- Use `PERKWATCH_DATA_DIR`; the local default root is `data/real/`.
- Keep real benefits, statements, CSV/OFX exports, credentials, databases, search files, and generated output out of git.
- User login, MFA, CAPTCHA, account selection, and consent remain manual.
- Stage user-supplied files with `perk_watch.staging.raw_data` so hashes and source records are written; then run `scripts/prepare_data.py` to normalize and index them.
- Never replace tracked evaluation examples with real data.
- During LLM merchant matching, send only a cleaned merchant description and a fixed merchant list. Keep amounts, dates, account details, filenames, and complete transaction rows local. Save uncertain results as `unknown`.

## Community collection

Public Reddit collection is an explicit offline action. It never runs from the application or while answering a user question.

- Store only post/comment IDs, public URLs, source and collection dates, short paraphrases, derived ideas, benefit IDs, and model-check metadata under `PERKWATCH_DATA_DIR/raw/<card>/community/<collection-version>/`.
- Do not commit community sources, full discussions, usernames, credentials, cookies, session files, or private/deleted content.
- Use public pages without logging in. A login wall is a blocker.
- The application reads only prepared local data and makes no Reddit requests.

## Runtime

Runtime reads prepared local data only. It does not collect issuer data, import statements, contact Reddit, or change stored data while answering a question. Keep transactions in SQLite and use embedding search only for benefit text and community ideas.

## Safety boundaries

Do not add automated login, credential storage, bank/card APIs, cookie extraction, or live external lookup while answering user questions. Do not commit real card data, public-community data, provider session files, or full community discussions.

## Checks

Run the checks for the implementation being changed:

```sh
python3 scripts/check_local_data_guard.py
python3 -m unittest discover -s tests
```

Run the smallest additional tests that cover the change. Do not commit unless the user explicitly asks.
