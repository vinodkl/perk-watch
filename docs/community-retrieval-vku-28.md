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
corpus or making any community request. The reranker evaluation made the
allowed OpenAI model calls over prepared metadata:

- corpus: `community-reddit-2026-09-20.v2`
- terms: `terms-3e941d4c11315d20`
- served ideas: **10/10** current reviewed ideas, one per benefit
- evaluation queries: **10/10**, one per benefit; relevance is the complete
  served set for that benefit, matching the ticket's unranked baseline
- baseline Recall@5: **10/10 = 1.0**
- exact-index Recall@5: **10/10 = 1.0**, no improvement over baseline
- baseline MRR: **10.0/10 = 1.0**
- LLM-reranked MRR: **10.0/10 = 1.0**, using `gpt-4o-mini`; **10/10** calls
  succeeded and returned valid idea-id permutations
- quote-verbatim rate before/after: **0/10 = 0.0**; source bodies are not
  stored by design, and the prepared output contains paraphrases only
- staleness-flag rate before/after: **0/10 = 0.0**; stale rows are filtered by
  terms version rather than served with a flag

Failures: **0/10** reranker calls and **0** offline safety/metadata failures.
The genuine reranker run used only the existing prepared metadata and made no
community request. Because every benefit has exactly one served idea, the
measured MRR tie is unavoidable. The simpler unranked per-benefit baseline is
retained; the reranker remains cut.

Coverage gaps: queries are corpus-derived rather than human relevance labels,
and there is only one served idea per benefit. The optional embedding index is
also cut because its Recall@5 tied the baseline.

This cut does not remove the offline community pipeline or its conflicting-idea
safety corpus.
