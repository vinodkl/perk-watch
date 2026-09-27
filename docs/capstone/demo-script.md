# PerkWatch demo script (3 minutes)

One story: **a credit is about to expire → why → what to do → how do I know it's right.** Every capstone topic appears once: fetching and normalizing (step 1), tracker (step 2), RAG and agent loop (steps 3 and 4), evals (step 5).

The app runs on **synthetic demo data**, so it is safe to screen-share or record. Only step 5 touches my real data, and it prints counts only.

## Before you start (10 minutes earlier)

Run everything from the repository root. `OPENAI_API_KEY` must be in `.env` there (the API reads `.env` from the directory it starts in).

**1. Build the demo data root** (an empty folder outside the repo):

```sh
export DEMO="$HOME/perkwatch-demo"
uv run python scripts/build_demo_data.py --root "$DEMO"
uv run python scripts/prepare_data.py --data-dir "$DEMO"
```

The second command adds search embeddings and community blurbs (about 10 small OpenAI calls: 7 blurbs plus embeddings; took 6 seconds when tested). **Don't skip it:** without it the wallet Ask in step 4 has nothing to search.

**2. Start the API and UI** in two terminals. Ports 8001 and 5174 avoid clashing with a normal :8000 / :5173 session:

```sh
uv run --extra ui python scripts/serve.py --data-dir "$DEMO" --port 8001
```

```sh
cd web && PERKWATCH_API=http://127.0.0.1:8001 npm run dev -- --port 5174
```

**3. Open the browser** at `http://localhost:5174/?as_of=2026-09-26`. The `as_of` date pins the demo to "5 days before the quarter ends". Reload once so no old chat is showing.

**4. Prepare a third terminal** at the repo root with this typed but not run, and with `PERKWATCH_DATA_DIR` **unset** (so `--real` reads my real data, not the demo root):

```sh
uv run python evals/run.py --suite tracker --real
```

**5. Keep the fallback open** in a background tab: [perk-watch-capstone.md](perk-watch-capstone.md) with its three screenshots.

## The run

| Time | Step | Topic |
|---|---|---|
| 0:00–0:25 | Main page and the at-risk coupon | problem, fetching, normalizing |
| 0:25–1:00 | Resy benefit panel, period history | tracker |
| 1:00–1:40 | Per-benefit chat | agent loop, RAG by ID |
| 1:40–2:20 | Wallet Ask that calls `search_terms` | RAG (retrieval), agent loop |
| 2:20–3:00 | Eval run and results | evals |

### Step 1 (0:00–0:25): the at-risk coupon

**Show:** the main page. Point at the headline **"$182.95 is about to expire"**, the left summary (at risk, missed, captured), and the top coupon under **EXPIRING SOON**.

**Say:** "I wanted a tracker like MaxRewards, plus a chat. My old version returned 'unknown' for 63 of 63 benefits on my real data. The fix was simple: Amex already prints a statement credit line for every redemption, so one regex per credit in a hand-checked catalog tells me what I used. I export the CSV myself; there are no automated logins."

### Step 2 (0:25–1:00): benefit panel history

**Click:** **Details** on the **$400 Resy Credit** coupon.

**Show:** the three quarter dots (Q1 used, Q2 half, Q3 at risk), the three statement credit lines, **MISSED THIS YEAR $40** and **LEFT · 5 DAYS $45**.

**Say:** "The tracker walks every period of the year, not just this one. Q2 closed with $60 of $100 used, so $40 is counted as missed. Every number here comes from statements, not the model."

### Step 3 (1:00–1:40): per-benefit chat

**Click:** the suggestion **"How can I use what is left before it resets?"** (the answer takes a few seconds).

**Show:** the answer's first line states **$45** and **September 30**. Usually there is no TOOLS line under it.

**Say:** "Because we know which benefit this is, its status, terms and community tips are injected by ID. No retrieval needed, so no tool call. The prompt forces 'amount left and deadline' first, and code checks that every dollar amount in the answer exists in that context. Community tips below are labelled 'not official terms'."

### Step 4 (1:40–2:20): wallet Ask with search_terms

**Click:** **×** to close the panel, then the dark **Ask PerkWatch** button at the bottom right, then the suggestion **"Which credit covers airport security fast lanes?"**

**Show:** the answer names the **$219 CLEAR+ Credit**, and the line **TOOLS · search_terms** under it.

**Say:** "Here the credit isn't known in advance, so the agent calls `search_terms`: embedding search over the official terms. It's a small loop: 3 tools, at most 4 calls, then it must answer. Filtering search by the card a question names took retrieval from 7 out of 8 to 8 out of 8."

*Answers vary run to run. Point at the TOOLS line, not at exact wording.*

### Step 5 (2:20–3:00): eval run

**Run:** the prepared command in the third terminal (it finishes instantly and makes no network calls).

**Show:** `synthetic` → `"periods": 23`, and `real` → `"periods": 31, "matched": 31`, both with accuracy `1.0` and no mismatches.

**Say:** "My MaxRewards account is the answer key, kept local and never committed. The tracker matches it on 31 of 31 periods. The last full run also scored retrieval 8 of 8, chat code checks 5 of 5, and an LLM judge 4.2 out of 5. Honest gaps: 7 of 11 credit patterns haven't been seen on a real statement yet, and anniversary resets aren't modelled."

## If something fails

**No API key, or no network** (the chat shows "Sorry, that failed: ..."): switch to the fallback tab and show [img/02-benefit-chat.png](img/02-benefit-chat.png) and [img/03-wallet-ask.png](img/03-wallet-ask.png). Say the same talking points. Steps 1, 2 and 5 need no network and still run live.

**The UI won't load:** show the tracker in a terminal instead. It is the same output as the main page:

```sh
uv run python scripts/show_tracker.py --data-root "$DEMO" --as-of 2026-09-26
```

**Step 5 prints `"skipped": "no answer key ..."`:** `PERKWATCH_DATA_DIR` is still set to the demo root. Run `unset PERKWATCH_DATA_DIR` and rerun. If you'd rather not touch real data at all, drop `--real`: it then shows only the 23 synthetic periods, and you quote the 31/31 from the results table.

**A port is busy:** pick another pair and change both commands, for example `--port 8002` and `PERKWATCH_API=http://127.0.0.1:8002 npm run dev -- --port 5175`. Use `localhost` in the browser, not `127.0.0.1` (Vite listens on `localhost`).
