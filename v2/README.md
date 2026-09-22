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
