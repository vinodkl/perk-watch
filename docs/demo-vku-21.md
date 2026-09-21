# Three-minute PerkWatch demo script

**0:00–0:25, setup.** Say: “PerkWatch reads prepared local data. Real issuer terms and transactions stay local. The model can select tools, but deterministic code owns status, amounts, remaining value, deadlines, and eligibility.” Run:

```sh
set -a; . ./.env; set +a
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real .venv/bin/python scripts/perkwatch_cli.py --model gpt-4o-mini
```

**0:25–1:05, core briefing.** At `PerkWatch question:`, enter: `Which benefits are unused or partially used, and what expires first?` Point out the returned statuses, values, deadlines, evidence IDs, and the authority line. Say: “These values are evaluator output, not model arithmetic.”

**1:05–2:05, evidence-backed question.** Run again and enter: `What supports the hotel and travel-credit deadlines, and are there community tips?` Show the official clause citations and the community result. Say: “Official clauses support the claim. Community ideas are labelled non-authoritative and cannot change the result.”

**2:05–2:40, planner.** Point to `planner.actions` and `planner.dropped`. Say: “Researchers work per benefit. The deterministic planner drops anything over remaining value, past its deadline, or blocked by constraints.” Mention that no supervisor or graph runtime is needed for these fixed bounded steps.

**2:40–3:00, limitation and close.** Say: “This local demo has 188 unresolved merchant descriptors. For this demo only, they are treated outside active benefit groups, so false-unused results are possible. Human-labelled local accuracy is unavailable. The reproducible frozen benchmark is reported separately.” Stop at three minutes.

**Recording command:** use the command above with screen recording. Recording is manual and is the only uncompleted submission action; no video file is represented as committed evidence.
