---
type: explanation
---

# PerkWatch V2 design

PerkWatch is a local assistant that combines current card benefits, transactions, and public community ideas to answer questions about benefit usage.

## In short

PerkWatch collects data for two cards during a monthly update, prepares it for local use, and answers questions through a command-line agent. Official benefit text and community ideas use separate embedding searches, which compare the meaning of text. Transactions stay in SQLite so amounts, refunds, dates, and usage can be calculated with normal code.

## Problem

Card benefits have different limits, eligible merchants, and time periods. A cardholder can know that a benefit exists and still be unsure whether it has been used or when it expires.

PerkWatch answers questions such as:

- Which benefits still have value available this month?
- Which transactions used a specific benefit?
- What should I use before the end of the month?
- How do other cardholders use this benefit?

The first version covers Amex Platinum and Chase Sapphire Preferred. It runs locally and uses a command-line interface.

## Monthly update

After all delivery phases are complete, PerkWatch updates local data once a month. The monthly update is user-assisted because issuer login, multifactor authentication, account selection, and transaction export remain manual.

The update has three steps:

1. Run the card-data collection skill for both cards. The user logs in, saves the latest benefit information, and exports transactions from January 1 through the current date.
2. Run the community collection skill. It reads public Reddit pages without logging in and saves public IDs, links, source and collection dates, short paraphrases, benefit IDs, derived ideas, and model checks. It does not save usernames or full discussions.
3. Run `v2/scripts/prepare_data.py`. It updates SQLite and rebuilds the benefit and community searches.
4. Run `python3 v2/scripts/check_local_data_guard.py` to confirm that local data is not tracked by git.

Repeated transaction exports may overlap. Preparation removes duplicates. Benefit information that has not changed does not need extra processing.

All collected and prepared data stays under `PERKWATCH_DATA_DIR`, normally `data/real/`. The directory is excluded from git. Runtime questions never contact an issuer or Reddit.

## Preparation

One command prepares all collected files, but the implementation is split into smaller files with clear responsibilities. `v2/scripts/prepare_data.py` is the V2 entry point and will rebuild both searches by Phase 4.

Preparation performs these jobs:

- Read benefit information for both cards.
- Ask an LLM to turn benefit text into structured fields.
- Import and clean transaction exports.
- Match transaction descriptions to merchants when needed.
- Validate each saved community model check against the current benefit terms.
- Keep only ideas marked `no_known_conflict`, and exclude checks based on older benefit information.
- Write benefit and transaction data to SQLite.
- Build the benefit search and community search.
- Write a short report with counts, skipped items, and unresolved fields.

The LLM may extract a benefit amount, time period, eligible merchants, enrollment requirement, and booking requirement. An extracted result is accepted automatically only when it matches the required JSON format, contains valid values, and points back to supporting benefit text. Missing or unclear values are stored as `unknown`.

Merchant matching sends only a cleaned merchant description and a fixed list of merchant names to the LLM. Amounts, dates, account details, filenames, and complete transaction rows stay local.

PerkWatch does not include a human review workflow. This keeps the project focused on retrieval, tools, and agent behavior. It also limits the claim: PerkWatch is an experimental assistant, not financial advice.

## Local data

PerkWatch has one local data folder with separate storage for different kinds of information.

```text
data/real/
  raw/
    amex-platinum/
      benefits/
      transactions/
      community/<collection-version>/
      sources.json
    chase-sapphire-preferred/
      benefits/
      transactions/
      community/<collection-version>/
      sources.json
  prepared/
    perkwatch.sqlite
    benefit-search/
    community-search/
    report.json
```

SQLite stores structured benefit fields, card-to-benefit links, transactions, merchant matches, and source references. Benefit text and community ideas are stored with the text needed for embedding search.

Transactions are not embedded. SQLite queries are better suited to exact dates, amounts, refunds, and totals. The agent receives transaction results through tools instead of searching transaction rows by similarity.

## Search

PerkWatch uses two embedding searches because official benefit information and community ideas serve different purposes.

The benefit search returns official text that explains amounts, eligible purchases, time periods, enrollment, and other conditions. Results include source references that can be cited in an answer.

The community search returns source-linked ideas derived from public discussions. Preparation includes only ideas whose current-terms review found no known conflict. Every result includes its public link and is labeled as a suggestion rather than an official rule.

The first version uses basic embedding search with filters for card and benefit. Rewording questions and reordering search results are later experiments. They are added only when evaluation shows that basic search misses useful results.

## CLI agent

The first user experience is a command-line interface. A short tool-selection loop with a fixed call limit receives a question, chooses tools, reads their results, and produces an answer with citations and supporting transaction references.

The agent has a maximum number of tool calls and retries. It cannot fetch new data, modify stored rules, or contact external sources while answering a question.

A final answer may include:

- Benefit name and card.
- Used and remaining amount.
- Deadline or benefit period.
- Transactions supporting the calculation.
- Official benefit text and source reference.
- Optional community ideas and public links.

Exact amounts and dates come from tools. The LLM chooses tools and writes the explanation.

## Tools

The initial agent uses four tools.

### `search_benefits`

`search_benefits` finds relevant official benefit text. It accepts a question plus optional card and benefit filters, then returns matching text and source references.

### `evaluate_benefits`

`evaluate_benefits` reads SQLite and calculates used amount, remaining amount, deadline, and supporting transaction IDs for one or more benefits.

### `search_community_ideas`

`search_community_ideas` finds public usage ideas for selected benefits. Results remain suggestions and cannot change benefit calculations.

### `get_transaction_evidence`

`get_transaction_evidence` returns the transactions referenced by a calculation. It does not expose unrelated transactions.

## Evaluation

Evaluation uses a small set of questions with expected tool results. The first set covers direct benefit questions, refunds, unclear merchant descriptions, date limits, and questions that need both benefit text and transactions.

Code checks factual fields:

- Citation IDs exist in retrieved results.
- Amounts and dates match tool results.
- Transaction IDs came from the transaction tool.
- Community ideas are labeled as suggestions.

An LLM judge scores answer quality, including clarity, usefulness, whether the answer addresses the question, and whether the supplied evidence supports the explanation. The LLM judge does not decide whether an amount, date, transaction, or citation is factually correct.

The search experiments compare:

1. Basic embedding search.
2. Search after an LLM rewords the question.
3. Search that uses an LLM to reorder the first set of results.

The system comparison evaluates answering from search results without tools against the tool-using agent. Both approaches use the same questions and answer format.

## Delivery phases

PerkWatch is delivered in five phases so each phase leaves a working system.

### Phase 1: monthly update and local data

Collect both cards and community notes, implement the SQLite tables and prepared file layout, and make the preparation command repeatable.

### Phase 2: benefit search and calculations

Build benefit search, query transactions through SQLite, and produce a direct benefit summary without an agent.

### Phase 3: agent and CLI

Add `search_benefits`, `evaluate_benefits`, and `get_transaction_evidence`. Implement the short tool-selection loop with a fixed call limit, and return answers with official citations and supporting transaction IDs.

### Phase 4: community ideas

Build community search, add `search_community_ideas`, and include clearly labeled community suggestions in relevant answers.

### Phase 5: evaluation and search improvements

Run the question set, compare answers produced with and without tools, and test rewording questions and reordering search results. Keep an added search step only when it improves the results.

## Phase tickets

Implementation work is split into five tickets:

1. [Phase 1: Monthly update and local data](perk-watch-v2-phase-1-local-data.md)
2. [Phase 2: Benefit search and calculations](perk-watch-v2-phase-2-search-and-calculations.md)
3. [Phase 3: Agent and CLI](perk-watch-v2-phase-3-agent-and-cli.md)
4. [Phase 4: Community ideas](perk-watch-v2-phase-4-community-ideas.md)
5. [Phase 5: Evaluation and search improvements](perk-watch-v2-phase-5-evaluation.md)

## Code structure

PerkWatch keeps command files small and puts reusable code under `src/perk_watch/`.

```text
scripts/
  prepare_data.py
  check_local_data_guard.py
  show_benefits.py
  ask.py

src/perk_watch/
  prepare/
    run.py
    extract_benefits.py
    import_transactions.py
    prepare_community.py
    build_searches.py
  storage.py
  benefits.py
  search.py
  tools.py
  agent.py
  app.py

evals/
  cases.json
  run.py
```

`v2/scripts/prepare_data.py` parses command-line arguments and calls `prepare.run()`. Files under `prepare/` convert collected files into local data. The top-level `benefits.py` and `search.py` are used while answering questions. `app.py` exposes an `answer(question)` function used by the command-line interface and later by an API.

Clean code does not require one file per function. Each file owns one meaningful job. The project avoids generic helper folders, pass-through wrappers, and interfaces with only one implementation.

## Later API and UI

The command-line interface is the only user interface in the first version. A later API calls the same `answer(question)` function and returns the same structured answer. A later web UI calls that API.

Planning for an API means keeping command-line input and printing outside the agent and tool code. It does not require building an API or UI during the capstone.
