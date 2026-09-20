# PerkWatch agent instructions

## Scope

Keep `evals/data/frozen/` synthetic and reproducible. Real or personal card data and public-community provenance are local-only inputs under `PERKWATCH_DATA_DIR`.

## Execution order

Before choosing work, read `docs/architecture-flow.md` and check the current PerkWatch Capstone blocking relations in Linear. Linear status and blocking relations are the source of truth; the document explains the intended offline, online, and evaluation sequence. Do not start a blocked or below-the-line ticket unless the user explicitly changes the plan.

## Local raw data

Read `.agents/skills/local-card-data-staging/SKILL.md` before collecting or importing card data.

- Use `PERKWATCH_DATA_DIR`; this repository's configured local root is `data/real/`.
- Keep real benefits, statements, CSV/OFX exports, credentials, databases, indexes, and derived output out of git.
- Use `src/perk_watch/raw_data.py` for imports so content hashes and source records are written.
- Never edit or replace `evals/data/frozen/` with real data.
- User login, MFA, CAPTCHA, account selection, and any consent must remain manual.

## Community corpus collection

A dedicated offline corpus-setup job may make read-only, unauthenticated requests to public Reddit pages for the currently approved Slice scope. It may run only during an explicit collection action, never from application runtime or an end-user application query.

- Store only post/comment IDs, public URLs, source and fetch dates, short paraphrased excerpts, derived ideas, benefit IDs, and review metadata under `PERKWATCH_DATA_DIR/raw/<card>/community/<collection-version>/`.
- Do not commit community sources, snapshots, full threads, usernames, credentials, cookies, session artifacts, or private/deleted content.
- Do not automate login, solve CAPTCHA/MFA, or bypass access controls. A login wall is a blocker.
- Keep processing deterministic after capture: the application reads only prepared community data and makes no external community requests.

## Safety boundaries

Do not add automated login, credential storage, bank/card APIs, cookie extraction, or live external lookup from application runtime or end-user application queries. Do not commit real card data, public-community corpus data, provider session artifacts, or full community threads.

## Checks

Run the smallest relevant checks after changes:

```sh
python3 scripts/check_local_data_guard.py
python3 evals/scripts/validate_slice0.py
```

Do not commit unless the user explicitly asks.
