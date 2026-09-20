# VKU-28 community retrieval decision

The implementation is in `src/perk_watch/community_rag.py`. It reads only prepared
community snapshots, indexes rows labelled `no_known_conflict`, filters by
`benefit_id` and `terms_version`, and returns source date, URL, paraphrase,
corpus version, and `non-authoritative` / `unverified` labels. It has no fields
or code path for status, amount, remaining value, or deadline.

`explicit_conflict` and `unclear` rows are excluded before embedding and are
never returned. The build command is `scripts/build_community_index.py`; it
uses the project's `text-embedding-3-small` OpenAI adapter and NumPy cosine
exact search. The index path is under `PERKWATCH_DATA_DIR` and is gitignored.

## Offline measurement

Measured against the existing prepared snapshot only, without refreshing the
corpus or making a network request:

- corpus: `community-reddit-2026-09-20.v2`
- terms: `terms-3e941d4c11315d20`
- served ideas: **10/10** current reviewed ideas, one per benefit
- evaluation queries: **10/10**, one per benefit; relevance is the complete
  served set for that benefit, matching the ticket's unranked baseline
- baseline Recall@5: **10/10 = 1.0**
- exact-index Recall@5: **10/10 = 1.0**, no improvement over baseline
- baseline MRR: **10/10 = 1.0**
- reranked MRR: **0/0**, not run because the index did not improve and no
  reranker should be retained
- quote-verbatim rate: **0/0**, not computable from paraphrase-only metadata;
  no source body is stored by design
- staleness-flag rate: **0/10 = 0.0**, all returned rows are terms-version
  filtered; stale rows are excluded rather than flagged into output

Failures: **0** during the offline safety/metadata checks. Coverage gaps:
there are no relevance-labelled natural-language queries, no source bodies for
quote comparison, and no LLM reranker run because network access was
prohibited. The simpler unranked per-benefit baseline is therefore retained;
the optional embedding index and reranker are deliberately cut from the
served path.

This cut does not remove the offline community pipeline or its conflicting-idea
safety corpus.
