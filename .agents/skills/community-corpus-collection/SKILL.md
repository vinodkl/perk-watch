---
name: community-corpus-collection
description: Collect or refresh PerkWatch's local-only, read-only public Reddit community corpus for approved benefits. Always fetches fresh data into a new timestamped corpus version; never for application runtime or an end-user query.
---

# Community corpus collection

This skill always fetches fresh community data into a new corpus version; it
is not gated on any ticket or execution order. It is an offline setup task,
not an application feature: the finished application must read the local
snapshot and never contact Reddit. Read `AGENTS.md` for the local-data and
safety boundaries before collecting.

## Boundaries

- Use public, unauthenticated Reddit pages only. Open a scratch browser tab;
  never import a login, read cookies, solve a CAPTCHA, or bypass a login wall.
- Keep only post/comment IDs, public URLs, source/fetch dates, short
  paraphrases, derived ideas, benefit IDs, and review metadata. Never retain
  full threads, titles verbatim, usernames, vote counts, or private/deleted
  content.
- Store every real artifact under
  `PERKWATCH_DATA_DIR/raw/<card>/community/<collection-version>/`. Do not write
  real Reddit data to `evals/data/frozen/`, source code, or git.
- Read `.agents/skills/local-card-data-staging/SKILL.md` before using local
  issuer terms. Use terms and transaction data only locally; Slice 1.5 does
  not need transaction rows.

## Collect

1. Set `PERKWATCH_DATA_DIR` to the local root, normally `data/real/` in this
   repo. Name the new collection-version from today's date:
   `community-reddit-<YYYY-MM-DD>.v1`, bumping the `.vN` suffix when a
   same-date version already exists (e.g. `community-reddit-2026-09-20.v1` →
   `.v2`). Always create a fresh version; never overwrite an existing one.
2. Work one card directory at a time. Read its newly collected benefit guide
   and retain stable benefit IDs between monthly runs. Keep only benefit IDs,
   names, and source references in community records; verify IDs are unique
   before searching.
3. Choose public, benefit-relevant search terms and subreddit scope. Prefer
   `r/AmexPlatinum` for Amex benefits and `r/CreditCards` when it is a better
   fit. In a visible scratch browser tab, perform read-only searches. For each
   benefit, collect and deduplicate roughly 10–20 public post/comment sources.
   If none are usable, record `no_usable_ideas` with an empty source list.
4. Write `collection_results.json` using the schema of the existing local
   corpus. Do not copy a title or thread body into it. Each source needs kind,
   ID, URL, source date, fetch date, and `public_reddit` origin.
5. Read the locally staged issuer terms and derive concrete, short ideas only
   from relevant sources. Model-review every derived idea against the current
   terms version: `no_known_conflict`, `explicit_conflict`, or `unclear`.
   Treat `unclear` as not served.
6. Write `candidates.json`, `model_judgments.json`, and
   `collection_results.json` under the card's new collection-version directory.
   Record the terms version derived from the newly collected benefit sources.

## Prepare and verify

After every card's benefits, transactions, and community notes are collected:

```sh
PERKWATCH_DATA_DIR=data/real PYTHONPATH=src python3 scripts/prepare_data.py
python3 scripts/check_local_data_guard.py
```

The command writes only under `PERKWATCH_DATA_DIR/prepared/`. It rejects
community reviews tied to older benefit terms.

## Report

Report the corpus version, source count per benefit, served/conflicting/unclear
counts, terms version, and any login/access or terms-review blocker. Do not
print source text, usernames, transaction data, or account details. Do not
commit unless the user explicitly asks.
