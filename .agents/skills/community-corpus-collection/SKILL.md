---
name: community-corpus-collection
description: Collect or refresh PerkWatch's local-only community tips for tracked credits (tips.json per card) from public, unauthenticated sources. An offline setup task; never run for application runtime or an end-user question.
---

# Community tips collection

This skill refreshes the short, source-linked tips PerkWatch shows under "What
the community does" and feeds to the per-benefit chat. It is an offline setup
task: the application only reads the prepared snapshot and never contacts the
web. Read `AGENTS.md` for the local-data and safety boundaries before collecting.

## Boundaries

- Use public, unauthenticated pages only. Never log in, import cookies, solve a
  CAPTCHA, or bypass a login wall; a wall is a blocker to report, not to work around.
- Good sources: Frequent Miler, Doctor of Credit, The Points Guy, Thrifty
  Traveler, Upgraded Points, One Mile at a Time, AwardWallet, and public Reddit
  threads (r/AmexPlatinum, r/amex, r/churning, r/CreditCards) when reachable.
- Keep only paraphrased tips, public URLs, source titles, and dates. Never keep
  full threads or articles, verbatim quotes, usernames, or vote counts.
- Store real output only under `PERKWATCH_DATA_DIR/raw/<card-dir>/community/`
  (card-dir is the card ID with hyphens). Never write it to source code or git.

## Collect

1. Set `PERKWATCH_DATA_DIR` (normally `data/real/`). Read
   `src/perk_watch/catalog.json`: tips are collected only for its `benefit_id`s,
   one card at a time.
2. Before overwriting, copy an existing `tips.json` to
   `tips-<YYYY-MM-DD>.json` in the same folder so the previous set is kept.
3. For each benefit, find 2–4 practical, current ideas, favouring what to do
   late in a period with value left (for example, what to buy with a leftover
   quarterly credit). Check each idea against the benefit's official terms in
   the prepared `benefits` table; drop anything the terms rule out.
4. Paraphrase each tip in one sentence of at most 30 words. Put tips reported
   as no longer working in `no_longer_works` with the date they stopped, instead
   of `tips`. If sources disagree on a number, leave the number out.
5. Write `tips.json`:

   ```json
   {"collected_on": "YYYY-MM-DD",
    "tips": [{"benefit_id": "amex_platinum_400_resy_credit", "tip": "...",
              "source_url": "https://...", "source_title": "...",
              "source_date": "YYYY-MM-DD", "last_verified": "YYYY-MM-DD"}],
    "no_longer_works": [{"benefit_id": "...", "tip": "...", "source_url": "https://...", "as_of": "YYYY-MM"}]}
   ```

   Every tip needs a real `https://` URL that you opened or saw in search
   results. Preparation silently drops tips for unknown benefit IDs or non-https
   URLs, and reports how many.

## Prepare and verify

```sh
uv run python scripts/prepare_data.py --data-dir "$PERKWATCH_DATA_DIR"
python3 scripts/check_local_data_guard.py
```

Preparation loads the tips into SQLite and writes a one- to two-sentence blurb
per benefit. Blurbs are cached by a hash of their tips, so only benefits whose
tips changed cost a model call. Check `prepared/report.json` for the tip counts
and blurbs written.

## Report

Report per benefit the number of tips kept and moved to `no_longer_works`, any
benefit with zero tips, and any access blocker. Do not print tip sources in
bulk, usernames, transaction data, or account details. Do not commit unless the
user explicitly asks.
