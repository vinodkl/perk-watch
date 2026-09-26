# PerkWatch V2

PerkWatch V2 is the simplified implementation described in [`docs/explanation/perk-watch-v2-design.md`](../docs/explanation/perk-watch-v2-design.md).

All new implementation work goes in this folder. The existing project remains unchanged while V2 is built and evaluated.

## Structure

```text
v2/
  src/             application code
  scripts/          command-line entry points
  evals/            evaluation cases and runner
  tests/            focused behavior tests
  data/real/        local-only collected and prepared data
```

Files are added when their delivery phase begins. Command files stay small; reusable code belongs under `src/perk_watch/`.

## Evaluation

Run the synthetic evaluation from `v2/` with `uv run python evals/run.py`. It rebuilds and uses only `evals/fixture.sqlite`, never `data/real/`. The run needs `OPENAI_API_KEY` for query rewording, candidate reordering, the live agent, and the answer-quality judge. If the key is in the repository-root `.env`, load it with `set -a; source ../.env; set +a` from `v2/` first.

The first evaluation run found only **2/11** live-agent factual passes. Requiring exact benefit IDs from official search results, directing the agent to preserve `unknown` and stop, and automatically including the matching official terms with calculations/community results raised this to **11/11 in each of two reruns**. The runner checks facts in the visible answer as well as in tool results; its JSON output includes any failed case, question, tool results, answer, and reason.

On 10 cases with a labeled relevant benefit, basic search hit@5 was **10/10** in both reruns; question rewording also scored **10/10**, and LLM reordering put a relevant result first **10/10**. Basic search already ranked those targets first, so neither added step improved retrieval; neither is used at runtime.

Mean LLM-judge scores (1–5) were **4.77 relevance and 4.59 evidence support with the live agent**, versus **4.18 relevance and 3.41 evidence support without tools**. Each rerun used 44 search/judge calls plus 42–43 live-agent calls, about 75.6k–78.4k tokens total, two tool retries, and no API failures. The synthetic fixture uses word-count embeddings; results do not measure production retrieval quality.

### Using evals to improve the agent

Run the suite, inspect each `live_agent_failures` entry with its tool trace and rendered answer, then fix the shared cause rather than tuning a single question. Add a regression test for the behavior, rerun the full suite twice, and compare factual checks first; use the LLM judge only for answer quality, never factual correctness. Keep rewording or reranking out of runtime unless repeated runs beat basic search.
