# PerkWatch capstone submission

## What shipped

PerkWatch is an offline-prepared, evidence-backed benefits assistant. The core briefing reads a deterministic local registry and ledger. The conversational path uses an OpenAI ReAct selector, official clause citations, reviewed non-authoritative community ideas, and a multi-benefit planner. The model selects tools; it does not own facts.

**Authority vocabulary:** merchant resolution is model-authoritative and measured. Transaction occurrence/filtering, eligibility matching, period arithmetic, amounts, remaining value, deadlines, and status are deterministic.

## Evidence

| Result set | Exact result | Boundary |
|---|---:|---|
| Frozen status, tool path | 36/36 | synthetic, `slice0-2026-09-19.v1` |
| Frozen retrieval baseline status | 20/36 | synthetic, same cases |
| Frozen tool remaining/deadline | 36/36, 36/36 | synthetic, same cases |
| Conflicting ideas resisted | 3/3 | frozen safety corpus |
| Generated red-team resistance | 10/10 | evaluation-only, synthetic |
| Community Recall@5 | 10/10 baseline and index | real prepared corpus version `community-reddit-2026-09-20.v2` |
| Community MRR | 10.0/10 baseline and reranker | reranker cut on tie |
| Local human-labelled accuracy | unavailable | no labels; never replaced with synthetic counts |

The LLM-arithmetic ablation produced **0/36 errors** on `slice0-2026-09-19.v1` / `synthetic-2026-09-19.v1`; observed failures were `[]`. Every metric carries its dataset or corpus version, failures, and coverage gaps.

The local integration uses 82 benefit rows, 15 supported active benefits, 51 active rules, 1,375 transactions, 563 merchant decisions, and 188 unresolved descriptors. The demo treats those 188 as outside active groups, which can cause false-unused results. Local accuracy metrics remain unavailable.

## Reality and limits

Real: staged issuer guides, local transaction exports, model merchant resolution, persisted SQLite decisions, offline public Reddit collection, reviewed community ideas, official citations, and local end-to-end integration. Simulated: all frozen fixtures and safety cases. Deferred: query-time Reddit lookup, live account connectivity, email, notifications/scheduling, enrollment automation, non-observable-benefit sources, and cards outside the two-card scope.

Served community retrieval is kept, but the embedding index and reranker are cut after ties. The red-team agent is kept as evaluation-only. MCP wrapper, QLoRA merchant model, and vision PDF extraction are cut. Minimal conversational polish is kept for the demo. Extractor/Verifier and isolated per-benefit Researchers/Planner are multi-agent because they have bounded independent contexts; fixed corpus preparation is not. No supervisor/graph runtime is used because fixed typed dispatch is simpler and exposes the authority boundary.

## Effort reconciliation

Appendix B's corrected original estimate is **41–52 hours before later additions**. The current VKU-21 ticket is **4–5 hours**. Later additions were local real-data integration/fallback (VKU-27), served community retrieval measurement (VKU-28), and evaluation-only red-team coverage (VKU-20). Cuts were the measured-tie community reranker/index, MCP wrapper, QLoRA merchant model, vision PDF extraction, live integrations, and full conversational product polish. The final package therefore reports the original estimate, the current ticket estimate, and actual additions/cuts rather than silently absorbing below-the-line work.

## Run

```sh
set -a; . ./.env; set +a
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real .venv/bin/python scripts/llm_arithmetic_ablation.py --model gpt-4o-mini --output /tmp/perkwatch-ablation.json
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real .venv/bin/python scripts/final_report.py --ablation /tmp/perkwatch-ablation.json --output /tmp/perkwatch-final-report.json
PYTHONPATH=src PERKWATCH_DATA_DIR=data/real .venv/bin/python scripts/perkwatch_cli.py --model gpt-4o-mini
```

The only manual remainder is recording the video. No video file is claimed by this repository.
