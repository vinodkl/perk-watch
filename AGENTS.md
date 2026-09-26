# PerkWatch agent instructions

## Work routing

PerkWatch has two implementations:

- **V2 is the default for new work.** Keep V2 implementation under `v2/`. Read `docs/explanation/perk-watch-v2-design.md`, then read the ticket for the active V2 phase. The five core V2 phase tickets define delivery order until that work is mirrored in Linear; the optional Phase 6 Jev experiment follows Phase 5.
- **V1 is legacy.** For explicit V1 work, read `docs/architecture-flow.md` and check the current PerkWatch Capstone blocking relations in Linear. Linear remains the source of truth for V1 status and blocking relations.

Do not edit V1 code for a V2 ticket unless the user explicitly asks. V1 may be inspected for behavior, but V2 must not import V1 modules.

## Local card data

Read `.agents/skills/local-card-data-staging/SKILL.md` before collecting or importing card data.

- Use `PERKWATCH_DATA_DIR`. V1 uses `data/real/`; V2 uses `v2/data/real/` by default.
- Keep real benefits, statements, CSV/OFX exports, credentials, databases, search files, and generated output out of git.
- User login, MFA, CAPTCHA, account selection, and consent remain manual.
- For V1 imports, use `src/perk_watch/raw_data.py` so hashes and source records are written.
- Never replace tracked evaluation examples with real data.

## Community collection

Public Reddit collection is an explicit offline action. It never runs from the application or while answering a user question.

- Store only post/comment IDs, public URLs, source and collection dates, short paraphrases, derived ideas, benefit IDs, and model-check metadata under `PERKWATCH_DATA_DIR/raw/<card>/community/<collection-version>/`.
- Do not commit community sources, full discussions, usernames, credentials, cookies, session files, or private/deleted content.
- Use public pages without logging in. A login wall is a blocker.
- The application reads only prepared local data and makes no Reddit requests.

## Safety boundaries

Do not add automated login, credential storage, bank/card APIs, cookie extraction, or live external lookup while answering user questions. Do not commit real card data, public-community data, provider session files, or full community discussions.

## Checks

Run the checks for the implementation being changed.

V1:

```sh
python3 scripts/check_local_data_guard.py
python3 evals/scripts/validate_slice0.py
```

V2:

```sh
python3 v2/scripts/check_local_data_guard.py
python3 -m unittest discover -s v2/tests
```

Run the smallest additional tests that cover the change. Do not commit unless the user explicitly asks.
