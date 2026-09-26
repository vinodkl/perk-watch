# PerkWatch V2 Phase 3: Agent and CLI

Add a command-line agent that chooses official search and transaction tools. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

A user can ask a natural-language question and receive an answer supported by official benefit text and transaction evidence.

## Tools

Phase 3 exposes three tools:

- `search_benefits` finds official benefit text and source references.
- `evaluate_benefits` calculates status, used amount, remaining amount, deadline, reason, and supporting transaction IDs.
- `get_transaction_evidence` returns only the transactions referenced by a calculation.

Community search is added in Phase 4.

## Work

- [x] Add typed input and output records for each tool.
- [x] Implement a short tool-selection loop with a fixed call limit and retry limit.
- [x] Reject unknown tools, invalid inputs, and repeated identical calls.
- [x] Return tool errors to the LLM instead of hiding them.
- [x] Have the model select structured evidence indexes, then render only the selected tool results; it cannot supply free-form factual claims.
- [x] Add `app.answer(question)` as the shared entry point.
- [x] Add a small `scripts/ask.py` command-line interface.
- [x] Keep collection, preparation, database writes, and external fetching out of the question path.

## Done when

- The CLI answers direct benefit, transaction, remaining-value, and deadline questions.
- Every factual claim can be matched to a tool result.
- Every official citation came from `search_benefits`.
- The CLI stops cleanly at its call or retry limit.
- Invalid tool calls and unavailable data produce a clear answer rather than a guess.
- `app.answer(question)` contains no command-line input or printing code.

## Checks

- Test questions that require only official search, only calculation, and both tools.
- Test malformed tool input, duplicate calls, missing data, tool failure, and call-limit exhaustion.
- Verify that the question path makes no issuer or Reddit request and does not change local data.

## Depends on

[Phase 2: Benefit search and calculations](perk-watch-v2-phase-2-search-and-calculations.md).
