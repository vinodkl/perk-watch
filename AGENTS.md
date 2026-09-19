# PerkWatch agent instructions

## Scope

Keep the frozen synthetic evaluation reproducible. Real or personal data is local smoke-test input only.

## Local real-data staging

Read `.agents/skills/local-card-data-staging/SKILL.md` before collecting or importing card data.

- Use `PERKWATCH_DATA_DIR`; this repository's configured local root is `data/real/`.
- Keep real benefits, statements, CSV/OFX exports, credentials, databases, indexes, and derived output out of git.
- Use `src/perk_watch/staging.py` for imports so content hashes and manifests are written.
- Never edit or replace `data/frozen/` with real data.
- User login, MFA, CAPTCHA, account selection, and any consent must remain manual.

## Safety boundaries

Do not add automated login, credential storage, bank/card APIs, cookie extraction, or live Reddit lookup. Do not commit real data or provider session artifacts.

## Checks

Run the smallest relevant checks after changes:

```sh
python3 scripts/check_local_data_guard.py
python3 scripts/validate_slice0.py
```

Do not commit unless the user explicitly asks.
