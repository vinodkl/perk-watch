# PerkWatch V2 Phase 4: Community ideas

Add separate search for source-linked community ideas without changing official benefit calculations. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

Relevant answers may include public usage ideas that are clearly separated from official benefit facts.

## Work

- [ ] Build an embedding search over prepared community ideas.
- [ ] Filter by card, benefit, and the current benefit information.
- [ ] Index only ideas whose saved model check is `no_known_conflict`.
- [ ] Exclude conflicting, unclear, and outdated checks.
- [ ] Add `search_community_ideas` as the fourth agent tool.
- [ ] Return a public link and source date with every idea.
- [ ] Label every idea as a suggestion rather than an official rule.
- [ ] Keep community text from changing benefit status, amount, deadline, or transaction evidence.

## Done when

- The CLI can include relevant community ideas for a benefit.
- Every displayed idea has a source link and date.
- Official facts and community suggestions appear in separate answer fields or sections.
- Conflicting, unclear, and outdated ideas are not returned.
- Answers remain correct when community search is empty or unavailable.

## Checks

- Test benefit filtering, source links, missing ideas, outdated checks, and conflicting ideas.
- Test community text that contains instructions aimed at the agent.
- Confirm that adding or removing community ideas cannot change calculated benefit facts.

## Depends on

[Phase 3: Agent and CLI](perk-watch-v2-phase-3-agent-and-cli.md).
