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

- [ ] Store each question with expected tool results and required source IDs.
- [ ] Add code checks for amounts, dates, statuses, transaction IDs, and citations.
- [ ] Add an LLM judge for clarity, usefulness, relevance, and support from supplied evidence.
- [ ] Keep the LLM judge out of factual checks for amounts, dates, statuses, transactions, and citations.
- [ ] Compare answering from search results without tools against the tool-using agent.
- [ ] Compare basic embedding search against search after question rewording.
- [ ] Compare basic ranking against LLM-based reordering of the first results.
- [ ] Record latency, model calls, token use, failures, and retry counts.
- [ ] Keep an added search step only when it improves the results.

## Done when

- One command runs the complete V2 evaluation set.
- The report separates factual checks from LLM-judge scores.
- Results compare answers with and without tools using the same questions and answer format.
- Search results show whether rewording or reordering improved retrieval.
- Every failed case is listed with its question, tool results, answer, and failure reason.
- The README and demo use measured results rather than planned claims.

## Checks

- Run the evaluation more than once to expose unstable judge or model behavior.
- Confirm that changing answer wording cannot turn a wrong amount or citation into a passing factual result.
- Confirm that private transaction rows are not written to tracked evaluation output.

## Depends on

[Phase 4: Community ideas](perk-watch-v2-phase-4-community-ideas.md).
