# PerkWatch V2 Phase 2: Benefit search and calculations

Build official benefit search and exact benefit calculations before adding an agent. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

A command can show benefit usage, remaining value, deadlines, supporting transactions, and official source text without an LLM choosing tools.

## Work

- [ ] Build an embedding search over official benefit text prepared in Phase 1.
- [ ] Filter search by card, benefit, and relevant date.
- [ ] Return source references with every search result.
- [ ] Calculate benefit periods, eligible transactions, used amount, remaining amount, and deadline with normal code.
- [ ] Treat refunds and negative adjustments correctly.
- [ ] Return `unknown` when required benefit or transaction information is missing.
- [ ] Add `v2/scripts/show_benefits.py` to list current benefit status for both cards.
- [ ] Keep transactions in SQLite and out of embedding search.

## Done when

- A direct command shows all prepared benefits for both cards.
- Every result includes status, used amount, remaining amount, deadline, reason, and supporting transaction IDs.
- Official search results include source references.
- Refund, missing merchant, unclear eligibility, and date-limit cases have focused tests.
- No agent or community search is required for the command to work.

## Checks

- Test official search with direct questions, paraphrased questions, unrelated benefits, and older benefit text.
- Test calculations at monthly, quarterly, yearly, and account-year boundaries present in the two cards.
- Confirm that returned amounts and deadlines come from code rather than LLM text.

## Depends on

[Phase 1: Monthly update and local data](perk-watch-v2-phase-1-local-data.md).
