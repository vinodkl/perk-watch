# PerkWatch V2 Phase 5: Evaluation and search improvements

Measure whether answers are supported by tool results and whether extra search steps improve retrieval. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

The project reports what works, what fails, and whether rewording questions or reordering search results earns its added complexity.

## Evaluation set

Create a small set of questions covering:

- Direct benefit questions.
- Questions requiring official text and transactions.
- Refunds and negative adjustments.
- Unclear merchant descriptions.
- Monthly, quarterly, yearly, and account-year date limits.
- Missing information that should produce `unknown`.
- Community suggestions that must remain separate from official facts.

## Work

- [x] Store each question with expected tool results and required source IDs.
- [x] Add code checks for amounts, dates, statuses, transaction IDs, and citations.
- [x] Add an LLM judge for clarity, usefulness, relevance, and support from supplied evidence.
- [x] Keep the LLM judge out of factual checks for amounts, dates, statuses, transactions, and citations.
- [x] Compare answering from search results without tools against the tool-using agent.
- [x] Compare basic embedding search against search after question rewording.
- [x] Compare basic ranking against LLM-based reordering of the first results.
- [x] Record latency, model calls, token use, failures, and retry counts.
- [x] Keep an added search step only when it improves the results.

## Done when

- One command runs the complete V2 evaluation set.
- The report separates factual checks from LLM-judge scores.
- Results compare answers with and without tools using the same questions and answer format.
- Search results show whether rewording or reordering improved retrieval.
- Every failed case is listed with its question, tool results, answer, and failure reason.
- The README and demo use measured results rather than planned claims.

## Completion evidence

The first live evaluation passed only 2/11 factual cases. Inspecting the failed tool traces showed guessed benefit IDs, unnecessary alternative tool calls, and omitted official citations. The agent was changed to require IDs from official search results, preserve and stop on `unknown`, stop exploring alternatives, and include matching official terms whenever a calculation or community result is selected.

Two reruns then passed all 11/11 factual checks for both live-agent and fixed-fixture evaluation. The JSON output includes any failed case, question, actual tool results, answer, and failure reason. Across 10 cases with a relevant benefit ID, basic search reached 10/10 hit@5 in both reruns; rewording also scored 10/10 and LLM reordering put a relevant result first 10/10. Basic search already ranked each target first, so neither extra search step improved retrieval.

Live-agent versus no-tool mean judge scores (1–5) were 4.77/4.18 relevance and 4.59/3.41 evidence support. Each rerun used 44 search/judge calls plus 42–43 agent calls, about 75.6k–78.4k tokens total, two tool retries, and zero API failures. The deterministic word-count fixture validates evaluation behavior, not production retrieval quality.

## Checks

- [x] Run the evaluation more than once to expose unstable judge or model behavior.
- [x] Confirm that changing answer wording cannot turn a wrong amount or citation into a passing factual result.
- [x] Confirm that private transaction rows are not written to tracked evaluation output.

## Depends on

[Phase 4: Community ideas](perk-watch-v2-phase-4-community-ideas.md).
