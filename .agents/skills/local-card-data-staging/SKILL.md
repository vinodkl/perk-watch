---
name: local-card-data-staging
description: User-assisted, provider-agnostic staging of local card benefits and transaction exports for PerkWatch.
---

# Local card-data staging

Use this skill when collecting real card benefits or transaction exports for
local smoke testing. The workflow is provider-agnostic; issuer UI steps are
allowed to differ, but the privacy boundary does not.

## Non-negotiable boundaries

- The user logs in and completes MFA, CAPTCHA, account selection, and consent.
  Never enter, request, or store passwords, security answers, one-time codes,
  or recovery codes.
- Use the provider's visible, user-authorized UI. Do not call bank/card APIs,
  scrape cookies, automate login, or preserve browser session artifacts.
- Do not use live Reddit lookup. Manually supplied public benefit guides are
  sufficient for this workflow.
- Write real data only under `PERKWATCH_DATA_DIR`. Never write it to tracked
  fixtures, evaluation files, source code, or the repository root.

## Workflow

1. Read `AGENTS.md` and load the configured root. If `.env` is present, use
   its `PERKWATCH_DATA_DIR`; do not commit `.env`.
2. Open the issuer's site in the user's visible browser. If it is blocked in
   the in-app browser, use an approved local Chrome/Browser Use connection only
   after the user explicitly authorizes it.
3. Stop at the login wall. Ask the user to log in and finish MFA/CAPTCHA.
4. Capture the card's visible benefit dashboard or manually downloaded public
   benefit guide. Prefer the issuer's terms/details view over promotional copy.
5. Export transactions from January 1 through today as CSV or OFX. If the
   issuer offers a consolidated year-to-date export, prefer it over many
   overlapping files. Do not include pending charges unless the user asks for
   them.
6. Import files through the existing staging API:

   ```python
   from perk_watch.staging import import_benefit_guide, import_transactions

   import_benefit_guide(path, url=issuer_url)
   import_transactions(path)
   ```

   Set `PERKWATCH_DATA_DIR` in the shell before running the import. Imports are
   content-addressed and idempotent.
7. Remove temporary downloads from `~/Downloads` or `/tmp` after verifying the
   staged copies. Do not remove user files that were not created for this run.
8. Run `python3 scripts/check_local_data_guard.py` and the relevant frozen-data
   validators. Report provider, date range, file counts, and blockers without
   printing transaction rows, account numbers, or benefit membership numbers.

## Provider neutrality

Do not bake issuer selectors, account identifiers, or URLs into the staging
module. Provider-specific navigation belongs in the current browser session or
in a short follow-up note, never in credentials or a reusable login script.

A provider may expose benefits as a dashboard, PDF, HTML page, or modal list.
Capture what is actually available and report gaps, such as a summary page that
lists benefits without exposing full terms. Do not claim all benefits were
captured merely because a page displays an "all benefits" count.

## Data layout

The configured root contains:

- `raw/benefits/`: content-addressed guide or benefit-page captures.
- `raw/transactions/`: content-addressed CSV/OFX exports.
- `manifests/`: source type, URL or filename, UTC import timestamp, content
  hash, and optional terms version.
- `derived/registry/`, `derived/ledger/`, `derived/indexes/`: reserved for
  later local-only processing; never commit their contents.

Keep each provider's raw file separate. A shared root is fine; merging files
is not. Use manifests and source filenames to distinguish issuers until an
explicit schema change adds provider metadata.
