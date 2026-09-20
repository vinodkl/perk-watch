---
name: community-corpus-collection
description: Collect or refresh PerkWatch's local-only, read-only public Reddit community corpus for approved benefits. Use for an explicit Slice 1.5 collection/refresh, never for application runtime or an end-user query.
---

# Community corpus collection

Use this skill only after reading `AGENTS.md`. It is an offline setup task, not
an application feature: the finished application must read the local snapshot
and never contact Reddit.

## Boundaries

- Use public, unauthenticated Reddit pages only. Open a scratch browser tab;
  never import a login, read cookies, solve a CAPTCHA, or bypass a login wall.
- Keep only post/comment IDs, public URLs, source/fetch dates, short
  paraphrases, derived ideas, benefit IDs, and review metadata. Never retain
  full threads, titles verbatim, usernames, vote counts, or private/deleted
  content.
- Store every real artifact under
  `PERKWATCH_DATA_DIR/community/<corpus-version>/`. Do not write real Reddit
  data to `data/frozen/`, source code, or git.
- Read `.agents/skills/local-card-data-staging/SKILL.md` before using local
  issuer terms. Use terms and transaction data only locally; Slice 1.5 does
  not need transaction rows.

## Collect

1. Confirm this is an explicit collection or refresh and set
   `PERKWATCH_DATA_DIR` to the local root, normally `data/real/` in this repo.
2. For the demo scope, read benefit IDs from `data/frozen/terms/benefits.json`.
   For an all-benefit collection, normalize each staged issuer guide into a
   local-only `PERKWATCH_DATA_DIR/derived/registry/<issuer>-benefits.json`
   inventory first. Keep only stable IDs, benefit names, and source-line
   references, then verify IDs are unique before searching.
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
6. Write `candidates.json` and `model_judgments.json` beside the collection
   results. A corpus version must identify this collection; a terms version
   must identify the local terms reviewed.

## Freeze and verify

```sh
PERKWATCH_DATA_DIR=data/real PYTHONPATH=src \
  python3 scripts/freeze_community_corpus.py --version <corpus-version>
PERKWATCH_DATA_DIR=data/real PYTHONPATH=src \
  python3 scripts/validate_slice15.py --version <corpus-version>
python3 scripts/check_local_data_guard.py
python3 scripts/validate_slice0.py
```

The freeze writes only `PERKWATCH_DATA_DIR/community/<corpus-version>/snapshot/`.
It must not write `PERKWATCH_DATA_DIR/derived/indexes/community/`; that index
is a later, local RAG concern.

## Report

Report the corpus version, source count per benefit, served/conflicting/unclear
counts, terms version, and any login/access or terms-review blocker. Do not
print source text, usernames, transaction data, or account details. Do not
commit unless the user explicitly asks.
