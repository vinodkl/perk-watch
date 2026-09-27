# PerkWatch tracker prototype (throwaway)

**Question:** can PerkWatch, on real statements, show a MaxRewards-style benefit tracker (used / partial / missed / at risk per period), plus a per-benefit chat and a community blurb, using the V2 data we already have?

**Answer: yes.** Details are in the results below. Validated decisions go into the V3 plan (`docs/explanation/perk-watch-v3-benefit-tracker.md`). This folder is not production code: no tests, state in memory only.

## Run

```sh
uv run python prototype/tracker_proto.py --as-of 2026-09-26   # terminal view
uv run --extra ui python prototype/app_proto.py                # http://127.0.0.1:8765
uv run --extra ui python prototype/eval_proto.py               # E1-E3 (E2/E3 call OpenAI)
uv run python prototype/eval_proto.py --skip-llm               # E1 only
```

The real React app in `web/` now uses this API too (Phase 8 look, tracker layout):

```sh
uv run --extra ui python prototype/app_proto.py   # API on :8765
cd web && npm run dev                             # UI on :5173, proxies /api to :8765
```

Set `PERKWATCH_API` to point Vite at another API.

Reads `$PERKWATCH_DATA_DIR/prepared/perkwatch.sqlite` read-only (default `data/real`). Optional local files, never committed:

- `prototype/community_tips.json`: collected tips.
- `prototype/maxrewards_answer_key.json`: the E1 answer key, hand-transcribed from MaxRewards.

## What it is

| Layer | Prototype | File |
|---|---|---|
| Fetch | existing staged real CSVs, unchanged | V2 `staging/` |
| Normalize | 13-credit hand-checked catalog; match issuer credit lines by regex + card sign | `tracker_proto.py` |
| Tracker | every period Jan→today: used / partial / missed / pending / unmarked / at_risk / open | `tracker_proto.py` |
| RAG | chat gets the benefit's context directly; `search_terms` tool reuses V2 embeddings | `app_proto.py` |
| Agent | tool-calling chat (3 tools, max 4 calls), prose answers, `$` grounding check | `app_proto.py` |
| Community | tips file + V2 reviewed ideas → 2-sentence LLM blurb | `app_proto.py` |
| Evals | E1 tracker vs MaxRewards, E2 recall@3, E3 chat code checks + LLM judge | `eval_proto.py` |
| UI | tiles with period dots, totals strip, drawer with chat | `page_proto.html` |

## Results (real data, as of 2026-09-26, statements through 09-18/19)

- **E1 tracker vs MaxRewards: 31/31 periods correct on both status and amount.** All 14 issuer credits matched; 0 unmatched credit lines.
- **Totals:** captured **$635.33**, missed **$514.27**, at risk now **$137.95** (Walmart+ $12.95, Uber Cash $15, Resy $100, DoorDash $10). The Amex "left this period" figure is **$1,370.95**; MaxRewards shows "$1,371 left".
- **E2 retrieval: recall@3 = 7/8.** The miss: "Sapphire hotel credit via the bank's travel site" ranked Amex's hotel credit first.
- **E3 chat: 3/3 cases pass the code checks** (remaining $, deadline, no invented $, community labelled). **Mean judge score 4.33/5.**

## Learnings to fold into V3

1. **Credit-line patterns are enough to decide "used".** No merchant matching and no LLM. Keep `credit_pattern` per benefit, and report unmatched lines containing "credit".
2. **Six patterns are unverified:** Walmart+, Hotel, Airline, Oura, CLEAR, Equinox. They follow the observed "Platinum X Credit" naming, but no credit has posted yet to confirm them.
3. **Manual credits need persistent marks.** Uber Cash and DoorDash are in-app, so they never appear on a statement. The prototype keeps marks in memory. V3 needs `profile.json` (or a table).
4. **The chat called no tools in any E3 case,** because the injected context was enough. RAG earns its keep in the global Ask and cross-benefit questions. Add an E3 case that needs `search_terms` (for example "can I stack this with …") so the tool path is evaluated.
5. **Retrieval should filter or boost by card** when the question names one (the E2 miss). Embedding the card name into the benefit text is another option.
6. **Prompt tweak:** for "is it worth it for me", the answer should use the history ("missed 8 of 8 months"). The Walmart+ answer didn't.
7. **Data freshness is visible and matters.** Statements end on 09-18/19, so the page must show "statements through" prominently. The pending rule (10-day grace) didn't trigger here, but it is needed after each month-end.
