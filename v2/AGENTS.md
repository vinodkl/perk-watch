# PerkWatch V2 agent instructions

## Before work

Read `../docs/explanation/perk-watch-v2-design.md` and the ticket for the active phase. Complete phase dependencies in order unless the user explicitly changes the plan.

The phase tickets are:

1. `../docs/explanation/perk-watch-v2-phase-1-local-data.md`
2. `../docs/explanation/perk-watch-v2-phase-2-search-and-calculations.md`
3. `../docs/explanation/perk-watch-v2-phase-3-agent-and-cli.md`
4. `../docs/explanation/perk-watch-v2-phase-4-community-ideas.md`
5. `../docs/explanation/perk-watch-v2-phase-5-evaluation.md`
6. `../docs/explanation/perk-watch-v2-phase-6-jev-experiments.md` (optional, after Phase 5)

## Code scope

- Put all V2 implementation under `v2/`.
- Treat V1 as read-only reference. Do not import V1 modules into V2.
- Keep files under `v2/scripts/` limited to command-line input, output, and assembly.
- Put reusable behavior under `v2/src/perk_watch/`.
- Give each file one meaningful job. Avoid generic helper folders, pass-through wrappers, and interfaces with one implementation.
- Add files when their phase needs them rather than scaffolding later phases.

## Local data

Use `PERKWATCH_DATA_DIR`, with `v2/data/real/` as the local default. Keep collected and prepared real data out of git.

During LLM merchant matching, send only a cleaned merchant description and a fixed merchant list. Keep amounts, dates, account details, filenames, and complete transaction rows local. Save uncertain results as `unknown`.

## Runtime

Runtime reads prepared local data only. It does not collect issuer data, import statements, contact Reddit, or change stored data while answering a question. Keep transactions in SQLite and use embedding search only for benefit text and community ideas.

## Language

Use the plain terms from the V2 design: monthly update, collected data, prepared data, benefit search, community search, tool-selection loop, source reference, and evaluation set. Introduce a technical term only when the implementation needs it, and explain it in plain words.

## Checks

Run the smallest tests for the change. Once Phase 1 provides the commands, always run:

```sh
python3 v2/scripts/check_local_data_guard.py
python3 -m unittest discover -s v2/tests
```

Do not commit unless the user explicitly asks.
