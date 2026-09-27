# Visible LLM in the PerkWatch UI: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LLM and the agent loop visible in the UI (a weekly AI plan on the main page, a readable step list for every answer, source labels, an ask bar, agent-proposed "mark used", and questions that need several tool calls) while every amount, status and deadline still comes from the deterministic tracker.

**Architecture:** The backend adds one wallet "briefing" call that reuses the existing tool loop in `runtime/chat.py`, enriches each tool-trace entry with a one-line result summary, and adds a `propose_mark` tool that only *offers* a mark (the user's tap does the write, via the existing mark endpoint). The frontend (`web/src/main.tsx`, one file) renders the briefing, the agent's steps, the grounding result, source labels, an inline ask bar and proposal buttons. Evals gain a briefing case and a multi-step case.

**Tech Stack:** Python 3 (FastAPI, `unittest`), OpenAI `gpt-4o-mini` through the existing `_Session` loop, React + TypeScript (Vite, checked with `npx tsc -b`), plain CSS in `web/src/theme.css`.

**Spec:** The brainstorm in this session (ideas A to F). Decisions are recorded in "Design decisions" below. Background: `docs/explanation/perk-watch-v3-benefit-tracker.md`, `CONTEXT.md`, `AGENTS.md`.

## Design decisions

- **A. Weekly plan.** `GET /api/briefing?as_of=` runs the wallet agent with a briefing prompt. Cached **in memory** in the API process, keyed by `(as_of, marks, report.json finished_at)`; nothing is written to disk. The UI renders the tracker first and fills the plan in afterwards. On any failure the page still works and shows one muted line.
- **B. Show the agent's work.** Each `tool_trace` entry gets a `summary` string. Replies gain `amounts_checked` (distinct $ amounts found in context) and `model`. The UI shows numbered steps, "answered from context, no tools needed" when there were none, and "✓ N amounts found in your data" (wording matches the grounding check's real guarantee: the amount exists, not that it is the right one).
- **C. Source labels.** "FROM YOUR STATEMENTS" and "AI-WRITTEN" pills, plus one sentence under the legend explaining the split. Frontend only.
- **D. Agent proposes, user confirms.** New tool `propose_mark` returns a proposal; the reply carries `proposals`. The UI shows a "Mark used" button that calls the existing `POST /api/benefits/{id}/mark` with a new `used: true` flag so a tap can never *unmark*. No AGENTS.md rule change is needed (the write stays user-initiated); add one clarifying sentence.
- **E. Multi-step questions.** New eval check `min_tool_calls`, a wallet case that needs `get_benefit_status` on two credits plus tips, and a briefing eval case. `MAX_TOOL_CALLS` stays 4.
- **F. Ask bar.** An inline ask box with state-based suggestion chips under the plan, replacing the floating button. Submitting opens the Ask rail and sends the question.

## Global Constraints

- Every dollar amount, status, date and days-left figure comes from the tracker. The LLM never decides "used" and never produces an amount that is not in its context.
- The model may see a credit's terms, tips, usage amounts and dates, never transaction descriptions, account details, filenames or complete transaction rows (AGENTS.md).
- Runtime makes no web requests other than model calls, and writes nothing except user-initiated marks to `PERKWATCH_DATA_DIR/user/profile.json`.
- Do not stop the user's servers on :8000 and :5173. Use :8001 (API) and :5174 (UI) for checks; open `http://localhost:5174`.
- **Do not commit.** AGENTS.md says commit only when the user asks, and another session holds a commit freeze. Workers leave changes uncommitted; the orchestrator commits each phase on `v3/benefit-tracker` after the user says so.
- Do not edit `docs/capstone/` (owned by another session).
- Checks: `uv run --extra ui python -m unittest discover -s tests`, `python3 scripts/check_local_data_guard.py`, `cd web && npx tsc -b`.
- Match surrounding style: compact Python, one-line docstrings; TSX components in `main.tsx`; new CSS as one rule per line appended to `theme.css`.

## Review Focus

1. **No API key or no network:** the main page must render fully; the plan area shows "The AI plan is unavailable (…)" and a 503 is never cached. Pinned by `test_briefing_without_openai_key_is_503_and_not_cached` (Task 3) and the Task 6 manual check.
2. **Nothing at risk** (e.g. `as_of=2026-10-01`): the plan must still read sensibly and the eval check `names_top_at_risk` must pass when there is nothing to name. Pinned in Task 8 (`test_min_tool_calls_and_top_at_risk_checks`) and the Task 6 manual check.
3. **Duplicate or stale fetches** (React StrictMode double effects, quick `as_of` changes): one LLM call per cache key, and an old reply never overwrites a newer date. Client promise cache + `live` flag in Task 5; server cache test in Task 3.
4. **Tool errors in the step list:** a bad benefit ID must show `error: …` as the step summary, not crash the UI. Pinned by `test_summarize_result_covers_each_tool_and_errors` (Task 1).
5. **Tapping "Mark used" on a period that is already marked** must leave it marked. Pinned by `test_mark_with_used_true_never_unmarks` (Task 7).

---

## Execution: who does what

Two phases, each with **two parallel workers** (subagents or Superset sessions) split by file ownership, then one integration task done by the orchestrator. Workers run in the main working copy (file sets don't overlap) and do not commit.

| Phase | Backend worker owns | Frontend worker owns | Orchestrator |
|---|---|---|---|
| 1 (A + B) | Tasks 1 to 3: `src/perk_watch/runtime/chat.py`, `src/perk_watch/api/app.py`, `tests/test_tracker.py`, `tests/test_api.py` | Tasks 4 and 5: `web/src/main.tsx`, `web/src/theme.css` | Task 6 |
| 2 (C to F) | Tasks 7 and 8: same backend files plus `evals/suites.py`, `evals/cases.json`, `tests/test_eval_runner.py` | Tasks 9 to 11: `web/src/main.tsx`, `web/src/theme.css` | Task 12 |

**Precondition:** none of these files are under `docs/capstone/`, and nothing is committed, so Phase 1 can start during the other session's commit freeze. The phase commits wait for that freeze to lift and for the user's approval.

**API contract both workers build against (Phase 1):**

```ts
type Step = { tool: string; args: Record<string, unknown>; summary: string }
type Reply = { answer: string; tool_trace: Step[]; unverified_amounts: string[]; amounts_checked: number; model: string }
// POST /api/benefits/{id}/chat and POST /api/ask return Reply.
// GET /api/briefing?as_of=YYYY-MM-DD returns Reply & { cached: boolean }; 503 {detail} when no key.
```

**Phase 2 addition:**

```ts
type Proposal = { benefit_id: string; title: string; period_start: string; period_label: string; amount: number }
// Reply gains proposals: Proposal[] (always present, may be empty).
// POST /api/benefits/{id}/mark accepts optional used: boolean. used=true on a marked period is a no-op.
```

---

## Phase 1: weekly plan (A) and visible agent steps (B)

### Task 1: Tool-step summaries and reply metadata

**Files:**
- Modify: `src/perk_watch/runtime/chat.py` (add `summarize_result`; change `_Session.converse` return, lines 111-135)
- Test: `tests/test_tracker.py` (`ChatTest`)
- Modify: `tests/test_api.py:108` (exact reply dict gains two keys)

**Interfaces:**
- Produces: `summarize_result(name: str, result: object) -> str`; every `converse` reply is `{"answer", "tool_trace": [{"tool", "args", "summary"}], "unverified_amounts", "amounts_checked": int, "model": str}`.

- [ ] **Step 1: Write the failing tests** (append to `ChatTest` in `tests/test_tracker.py`; add `summarize_result, MODEL` to the `perk_watch.runtime.chat` import)

```python
    def test_summarize_result_covers_each_tool_and_errors(self):
        status = {"title": "$400 Resy Credit", "current_period": {"remaining": 45.0, "status": "at_risk"}}
        self.assertEqual(summarize_result("get_benefit_status", status), "$400 Resy Credit: $45.00 left, at_risk")
        self.assertEqual(summarize_result("search_terms", [{"title": "$219 CLEAR+ Credit"}, {"title": "$200 Airline Fee Credit"}]),
                         "found $219 CLEAR+ Credit, $200 Airline Fee Credit")
        self.assertEqual(summarize_result("search_terms", []), "no matching terms")
        self.assertEqual(summarize_result("get_community_tips", [{"tip": "a"}]), "1 community tip")
        self.assertEqual(summarize_result("get_community_tips", []), "0 community tips")
        self.assertEqual(summarize_result("get_benefit_status", {"error": "not a tracked benefit; tracked ids: [...]"}),
                         "error: not a tracked benefit; tracked ids: [...]")

    def test_reply_reports_step_summary_amounts_checked_and_model(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_benefit_status", arguments=json.dumps({"benefit_id": RESY})))
        client = FakeClient([_message(tool_calls=[call]), _message("You have $100 left, $100 by Sep 30.")])
        reply = benefit_chat(db, RESY, [{"role": "user", "content": "How do I use it?"}], as_of=date(2026, 9, 26), client=client)
        self.assertEqual(reply["tool_trace"], [{"tool": "get_benefit_status", "args": {"benefit_id": RESY},
                                                "summary": "$400 Resy Credit: $100.00 left, at_risk"}])
        self.assertEqual((reply["amounts_checked"], reply["model"]), (1, MODEL))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --extra ui python -m unittest tests.test_tracker.ChatTest -v`
Expected: FAIL with `ImportError: cannot import name 'summarize_result'`

- [ ] **Step 3: Implement** in `src/perk_watch/runtime/chat.py`

Add after `unverified_amounts`:

```python
def summarize_result(name: str, result: object) -> str:
    """One line for the UI's step list: what a tool call found. Never transaction text."""
    if isinstance(result, dict) and "error" in result:
        return f"error: {str(result['error'])[:120]}"
    if name == "get_benefit_status" and isinstance(result, dict):
        current = result["current_period"]
        return f"{result['title']}: ${current['remaining']:.2f} left, {current['status']}"
    if name == "search_terms" and isinstance(result, list):
        return "found " + ", ".join(hit["title"] for hit in result) if result else "no matching terms"
    if name == "get_community_tips" and isinstance(result, list):
        return f"{len(result)} community tip{'' if len(result) == 1 else 's'}"
    return ""
```

In `_Session.converse`, replace the return and the `trace.append` line:

```python
            if not message.tool_calls:
                answer = message.content or ""
                return {"answer": answer, "tool_trace": trace,
                        "unverified_amounts": unverified_amounts(answer, "\n".join(evidence)),
                        "amounts_checked": len({_norm(m) for m in _MONEY.findall(answer)}), "model": self.model}
```

```python
                trace.append({"tool": call.function.name, "args": args,
                              "summary": summarize_result(call.function.name, result)})
```

- [ ] **Step 4: Update the exact-dict assertion** in `tests/test_api.py` `test_chat_and_ask_use_injected_client`:

```python
        self.assertEqual(reply, {"answer": "You have $100 left on Resy.", "tool_trace": [], "unverified_amounts": [],
                                 "amounts_checked": 1, "model": "gpt-4o-mini"})
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run --extra ui python -m unittest tests.test_tracker tests.test_api tests.test_eval_runner -v`
Expected: all PASS (the eval runner reads `tool_trace[*]["tool"]` only, so the extra key is harmless).

- [ ] **Step 6: Leave uncommitted** (see Global Constraints).

### Task 2: `wallet_briefing`

**Files:**
- Modify: `src/perk_watch/runtime/chat.py` (add `BRIEFING_SYSTEM`, `BRIEFING_REQUEST`, `_wallet_context`, `wallet_briefing`; make `wallet_ask` use `_wallet_context`)
- Test: `tests/test_tracker.py` (`ChatTest`)

**Interfaces:**
- Consumes: the Task 1 reply shape.
- Produces: `wallet_briefing(db, *, as_of: date, marks: Marks | None = None, client=None, embedder=None, model: str = MODEL) -> dict` (same shape as Task 1); `BRIEFING_SYSTEM: str`.

- [ ] **Step 1: Write the failing test** (add `wallet_briefing, BRIEFING_SYSTEM` to the chat import)

```python
    def test_briefing_uses_wallet_context_tools_and_no_transaction_text(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_community_tips", arguments=json.dumps({"benefit_id": RESY})))
        client = FakeClient([_message(tool_calls=[call]), _message("- **$400 Resy Credit**: $100 left by Sep 30.")])
        reply = wallet_briefing(db, as_of=date(2026, 9, 26), client=client)
        first = client.requests[0]["messages"]
        self.assertEqual(first[0]["content"], BRIEFING_SYSTEM)
        self.assertTrue(first[1]["content"].startswith("WALLET CONTEXT:"))
        self.assertNotIn("COFFEE", first[1]["content"])
        self.assertEqual(first[2], {"role": "user", "content": "Write this week's plan."})
        self.assertEqual(reply["tool_trace"], [{"tool": "get_community_tips", "args": {"benefit_id": RESY}, "summary": "0 community tips"}])
        self.assertEqual((reply["unverified_amounts"], reply["amounts_checked"]), ([], 2))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra ui python -m unittest tests.test_tracker.ChatTest.test_briefing_uses_wallet_context_tools_and_no_transaction_text -v`
Expected: FAIL with `ImportError: cannot import name 'wallet_briefing'`

- [ ] **Step 3: Implement**

Add after `WALLET_SYSTEM`:

```python
BRIEFING_SYSTEM = """You write a short plan for this week, shown at the top of a cardholder's credit tracker.
Rules:
- Dollar amounts, dates and days left must come from the WALLET CONTEXT or tool results. Never invent them.
- Write exactly 3 bullets, most urgent first: at_risk credits (value left, ending soon), then the largest open balances.
- Each bullet starts with the benefit title in bold, then the amount left and the deadline, then one concrete action.
- Call get_community_tips for the most urgent credit and add its best idea to that bullet, labelled "Community idea".
- For manual credits (tracking = manual), remind the user to mark them once used.
- If nothing is at_risk, say so in the first bullet and plan around the largest open balances.
- No greeting, no intro line, no closing line."""

BRIEFING_REQUEST = "Write this week's plan."
```

Replace `wallet_ask` with:

```python
def _wallet_context(db: sqlite3.Connection, as_of: date, marks: Marks | None) -> str:
    """Current period of every credit, without per-period history, to keep the context small."""
    wallet = []
    for state in track(db, as_of, marks)["benefits"]:
        item = compact_status(state, as_of)
        item.pop("history")
        wallet.append(item)
    return "WALLET CONTEXT:\n" + json.dumps(wallet, indent=1)


def wallet_ask(db: sqlite3.Connection, messages: list[dict], *, as_of: date, marks: Marks | None = None,
               client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    session = _Session(db, as_of, marks, client, embedder, model)
    return session.converse(WALLET_SYSTEM, _wallet_context(db, as_of, marks), messages)


def wallet_briefing(db: sqlite3.Connection, *, as_of: date, marks: Marks | None = None,
                    client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    session = _Session(db, as_of, marks, client, embedder, model)
    return session.converse(BRIEFING_SYSTEM, _wallet_context(db, as_of, marks),
                            [{"role": "user", "content": BRIEFING_REQUEST}])
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra ui python -m unittest tests.test_tracker tests.test_api -v`
Expected: all PASS (`$400` is in the title and `$100` is `remaining`, so both are found: `amounts_checked == 2`).

- [ ] **Step 5: Leave uncommitted.**

### Task 3: `GET /api/briefing` with an in-memory cache

**Files:**
- Modify: `src/perk_watch/api/app.py` (import `wallet_briefing`; add `report()` helper, `briefings` cache, the route; make `status()` use `report()`)
- Test: `tests/test_api.py` (`ApiTest`)

**Interfaces:**
- Consumes: `wallet_briefing` (Task 2).
- Produces: `GET /api/briefing?as_of=` returning Task 1 shape plus `"cached": bool`; 503 `{"detail": ...}` when the key is missing.

- [ ] **Step 1: Write the failing tests**

```python
    def test_briefing_is_cached_until_marks_change(self):
        fake = FakeClient([_message("- **$400 Resy Credit**: $100 left."), _message("- Mark Uber Cash once used.")])
        client = TestClient(create_app(self.root, chat_client=fake))
        first = client.get("/api/briefing", params={"as_of": AS_OF}).json()
        again = client.get("/api/briefing", params={"as_of": AS_OF}).json()
        self.assertEqual((first["cached"], again["cached"], len(fake.requests)), (False, True, 1))
        self.assertEqual(first["answer"], again["answer"])
        client.post(f"/api/benefits/{UBER_CASH}/mark", json={"period_start": "2026-09-01", "as_of": AS_OF})
        after = client.get("/api/briefing", params={"as_of": AS_OF}).json()
        self.assertEqual((after["cached"], after["answer"], len(fake.requests)), (False, "- Mark Uber Cash once used.", 2))

    def test_briefing_without_openai_key_is_503_and_not_cached(self):
        with patch("perk_watch.embeddings._api_key", return_value=None):
            self.assertEqual(self.client.get("/api/briefing", params={"as_of": AS_OF}).status_code, 503)
            self.assertEqual(self.client.get("/api/briefing", params={"as_of": AS_OF}).status_code, 503)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --extra ui python -m unittest tests.test_api -v`
Expected: the two new tests FAIL with 404.

- [ ] **Step 3: Implement** in `src/perk_watch/api/app.py`

Import: `from ..runtime.chat import benefit_chat, wallet_ask, wallet_briefing`

Inside `create_app`, after `require_benefit`:

```python
    def report() -> dict:
        try:
            return json.loads((data_root(root) / "prepared" / "report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # In memory only: runtime never writes prepared data. A new mark or a re-prepare changes the key.
    briefings: dict[tuple, dict] = {}
```

Route, after `ask`:

```python
    @app.get("/api/briefing")
    def briefing(as_of: date | None = None) -> dict:
        day, current = as_of or date.today(), marks()
        key = (day.isoformat(), tuple(sorted(current.items())), report().get("finished_at"))
        if key in briefings:
            return {**briefings[key], "cached": True}
        with connection() as db:
            try:
                briefings[key] = wallet_briefing(db, as_of=day, marks=current, client=chat_client, embedder=embedder)
            except RuntimeError as error:
                raise HTTPException(503, str(error))
        return {**briefings[key], "cached": False}
```

Change `status()` to use it:

```python
    @app.get("/api/status")
    def status() -> dict:
        with connection() as db:
            through = data_through(db)
        return {"last_preparation_time": report().get("finished_at"), "data_through": through}
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --extra ui python -m unittest discover -s tests`
Expected: all tests PASS (67 existing + 5 new = 72).

- [ ] **Step 5: Leave uncommitted.**

### Task 4: Agent step list in chat answers (B, frontend)

**Files:**
- Modify: `web/src/main.tsx` (types near line 20; `Chat` lines 230-257; `BenefitRail` and `AskRail` pass `emptyNote`)
- Modify: `web/src/theme.css` (append rules)

**Interfaces:**
- Consumes: the Phase 1 API contract (`Reply`, `Step`).
- Produces: `type Step`, `type Reply`, `function AgentTrace({ reply, emptyNote }: { reply: Reply; emptyNote: string })`, CSS class `.source.ai`. Task 5 and Phase 2 reuse all three.

- [ ] **Step 1: Replace the `Msg` type** (line 20) with:

```ts
type Step = { tool: string; args: Record<string, unknown>; summary: string }
type Reply = { answer: string; tool_trace: Step[]; unverified_amounts: string[]; amounts_checked: number; model: string }
type Msg = { role: 'user' | 'assistant'; content: string; reply?: Reply; pending?: boolean }
```

- [ ] **Step 2: Add `AgentTrace`** above `function Chat`:

```tsx
function AgentTrace({ reply, emptyNote }: { reply: Reply; emptyNote: string }) {
  const steps = reply.tool_trace
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  return <div className="agent-trace">
    <p className="agent-meta"><span className="source ai">AI · {reply.model}</span> {steps.length ? plural(steps.length, 'tool call') : emptyNote}</p>
    {!!steps.length && <ol className="agent-steps">{steps.map((s, i) => <li key={i}>
      <code>{s.tool}</code>{typeof s.args.query === 'string' && <span> “{s.args.query}”</span>}{s.summary && <span className="step-result"> → {s.summary}</span>}
    </li>)}</ol>}
    {reply.unverified_amounts.length
      ? <p className="unverified">⚠ Not found in your data: {reply.unverified_amounts.join(', ')}</p>
      : reply.amounts_checked > 0 && <p className="verified">✓ {plural(reply.amounts_checked, 'amount')} found in your data</p>}
  </div>
}
```

- [ ] **Step 3: Update `Chat`.** Add an `emptyNote: string` prop. In `send`, type the call as `api<Reply>(...)` and store the reply:

```tsx
      const reply = await api<Reply>(endpoint, { messages: history.map(({ role, content }) => ({ role, content })), as_of: asOf })
      setMessages([...history, { role: 'assistant', content: reply.answer, reply }])
```

Replace the two trace lines in the message render (old lines 251-252) with:

```tsx
      {m.reply && <AgentTrace reply={m.reply} emptyNote={emptyNote}/>}
```

Pass `emptyNote="answered from this benefit's context, no tools needed"` from `BenefitRail` and `emptyNote="answered from your wallet, no tools needed"` from `AskRail`.

- [ ] **Step 4: Append CSS** to `web/src/theme.css`:

```css
.source{display:inline-block;font:10px 'IBM Plex Mono',monospace;letter-spacing:.06em;border-radius:10px;padding:2px 7px;vertical-align:middle}
.source.ai{color:#5c4bf5;background:#ebe8ff}
.agent-trace{margin-top:8px;padding:8px 10px;background:#eee4cf;border-radius:10px;font:11px/1.5 'IBM Plex Mono',monospace;color:#5d4f3f}
.agent-meta{margin:0}
.agent-steps{margin:6px 0 0;padding-left:18px}
.agent-steps li{margin:2px 0;overflow-wrap:anywhere}
.agent-steps code{color:#2a2118;font-weight:700}
.step-result{color:#277445}
.verified{margin:6px 0 0;color:#277445}
.agent-trace .unverified{font-family:'Public Sans','Arial',sans-serif}
```

- [ ] **Step 5: Type-check**

Run: `cd web && npx tsc -b`
Expected: no output, exit 0. (Old `.ask-trace` CSS may stay; it is now unused.)

- [ ] **Step 6: Leave uncommitted.**

### Task 5: "This week's plan" on the main page (A, frontend)

**Files:**
- Modify: `web/src/main.tsx` (add `Briefing` component and its cache; render it in `App` after the `.welcome` div, line 117)
- Modify: `web/src/theme.css` (append rules)

**Interfaces:**
- Consumes: `Reply`, `AgentTrace`, `Markdown`, `api` (Task 4 and existing code); `GET /api/briefing`.
- Produces: `function Briefing({ tracker }: { tracker: Tracker })`.

- [ ] **Step 1: Add the component** above `function Legend`:

```tsx
// One request per as-of date and totals: StrictMode's double effects and re-renders reuse the same promise.
const briefingCache = new Map<string, Promise<Reply>>()

function Briefing({ tracker }: { tracker: Tracker }) {
  const key = `${tracker.as_of}|${JSON.stringify(tracker.totals)}`
  const [state, setState] = React.useState<{ reply?: Reply; error?: string }>({})
  React.useEffect(() => {
    let live = true
    setState({})
    if (!briefingCache.has(key)) briefingCache.set(key, api<Reply>(`/api/briefing?as_of=${encodeURIComponent(tracker.as_of)}`))
    briefingCache.get(key)!.then(reply => { if (live) setState({ reply }) },
      e => { briefingCache.delete(key); if (live) setState({ error: e instanceof Error ? e.message : String(e) }) })
    return () => { live = false }
  }, [key])
  return <section className="ai-plan" aria-live="polite">
    <h2 className="eyebrow">THIS WEEK'S PLAN <span className="source ai">AI-WRITTEN</span></h2>
    {state.error ? <p className="ai-plan-off">The AI plan is unavailable ({state.error}). Everything else on this page comes from your statements.</p>
      : !state.reply ? <p className="ai-plan-loading">Reading your credits and writing a plan…</p>
      : <><Markdown text={state.reply.answer}/><AgentTrace reply={state.reply} emptyNote="written from your wallet, no tools needed"/></>}
  </section>
}
```

- [ ] **Step 2: Render it** in `App`, directly after the closing `</div>` of `.welcome` and before the EXPIRING SOON section:

```tsx
        <Briefing tracker={tracker}/>
```

- [ ] **Step 3: Append CSS**

```css
.ai-plan{margin:6px 0 4px;padding:18px 22px;background:#fffdf8;border:1px solid #d9d3ff;border-radius:18px;box-shadow:0 10px 22px #392d1910;line-height:1.55}
.ai-plan .eyebrow{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.ai-plan ul{margin:6px 0;padding-left:20px}.ai-plan li{margin:4px 0}.ai-plan p{margin:0 0 6px}
.ai-plan-loading,.ai-plan-off{color:#766550;font-style:italic}
```

- [ ] **Step 4: Type-check**

Run: `cd web && npx tsc -b`
Expected: exit 0.

- [ ] **Step 5: Leave uncommitted.**

### Task 6: Phase 1 integration check (orchestrator)

- [ ] **Step 1: Full checks**

```sh
uv run --extra ui python -m unittest discover -s tests
python3 scripts/check_local_data_guard.py
cd web && npx tsc -b
```
Expected: 72 tests OK, guard clean, tsc exit 0.

- [ ] **Step 2: Run on demo data** (spare ports; the user's :8000/:5173 stay up)

```sh
export DEMO=/private/tmp/claude-501/-Users-vinod-ai-dev-perk-watch/<session>/scratchpad/demo
uv run python scripts/build_demo_data.py --root "$DEMO"     # skip if it exists
uv run python scripts/prepare_data.py --data-dir "$DEMO"    # embeddings + blurbs, ~10 small OpenAI calls
uv run --extra ui python scripts/serve.py --data-dir "$DEMO" --port 8001
cd web && PERKWATCH_API=http://127.0.0.1:8001 npm run dev -- --port 5174
```

- [ ] **Step 3: Check in the browser** at `http://localhost:5174/?as_of=2026-09-26`:
  - the tracker appears first, then the plan fills in with 3 bullets and a "get_community_tips → N community tips" step;
  - reloading does not make a new LLM call (API log shows one `/api/briefing` computing, the rest cached);
  - Resy "How can I use what is left" shows "answered from this benefit's context, no tools needed" and "✓ N amounts found";
  - wallet Ask "airport security" shows `search_terms “…” → found $219 CLEAR+ Credit, …`;
  - `?as_of=2026-10-01` (nothing at risk) gives a sensible plan (Review Focus 2);
  - with the API started without a key (`env -u OPENAI_API_KEY` and a directory with no `.env`), the page renders and the plan shows the unavailable line (Review Focus 1).
- [ ] **Step 4: Screenshot** the main page and both rails into the scratchpad for the user. Ask the user to review and to approve the Phase 1 commit.

---

## Phase 2: labels (C), agent proposals (D), multi-step (E), ask bar (F)

### Task 7: `propose_mark` tool and idempotent marks (D, backend)

**Files:**
- Modify: `src/perk_watch/runtime/chat.py` (tool definition, `run_tool`, `summarize_result`, `_Session.proposals`, prompts)
- Modify: `src/perk_watch/api/app.py` (`MarkRequest.used`, `mark` route)
- Test: `tests/test_tracker.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 reply shape.
- Produces: replies gain `"proposals": list[{"benefit_id", "title", "period_start", "period_label", "amount": float}]`; `MarkRequest.used: bool | None`.

- [ ] **Step 1: Write the failing tests** (`tests/test_tracker.py`, `ChatTest`)

```python
    def _propose(self, benefit_id, marks=None):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="propose_mark", arguments=json.dumps({"benefit_id": benefit_id})))
        client = FakeClient([_message(tool_calls=[call]), _message("Tap the button to confirm.")])
        return benefit_chat(fixture_db([]), benefit_id, [{"role": "user", "content": "I used it"}],
                            as_of=date(2026, 9, 26), marks=marks, client=client)

    def test_propose_mark_offers_the_current_manual_period(self):
        reply = self._propose(UBER_CASH)
        self.assertEqual(len(reply["proposals"]), 1)
        proposal = reply["proposals"][0]
        self.assertEqual((proposal["benefit_id"], proposal["period_start"], proposal["amount"]), (UBER_CASH, "2026-09-01", 15.0))
        self.assertTrue(reply["tool_trace"][0]["summary"].startswith("offered to mark $200 Uber Cash"))

    def test_propose_mark_refuses_auto_credits_and_marked_periods(self):
        self.assertEqual(self._propose(RESY)["proposals"], [])
        self.assertEqual(self._propose(UBER_CASH, marks={(UBER_CASH, "2026-09-01"): 1500})["proposals"], [])
```

And in `tests/test_api.py`:

```python
    def test_mark_with_used_true_never_unmarks(self):
        body = {"period_start": "2026-09-01", "as_of": AS_OF, "used": True}
        first = self.client.post(f"/api/benefits/{UBER_CASH}/mark", json=body).json()
        second = self.client.post(f"/api/benefits/{UBER_CASH}/mark", json=body).json()
        marked = lambda state: next(p for p in state["periods"] if p["start"] == "2026-09-01")["marked"]
        self.assertEqual((marked(first), marked(second)), (True, True))
```

Update the exact dict in `test_chat_and_ask_use_injected_client` to add `"proposals": []`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --extra ui python -m unittest tests.test_tracker tests.test_api -v`
Expected: FAIL (`KeyError: 'proposals'`; second mark unmarks).

- [ ] **Step 3: Implement the tool** in `chat.py`. Append to `TOOLS`:

```python
    {"type": "function", "function": {
        "name": "propose_mark", "description": "Offer the user a one-tap button to mark a manually tracked credit used for its current period. It marks nothing; the user must tap to confirm.",
        "parameters": {"type": "object", "properties": {"benefit_id": {"type": "string"}},
                       "required": ["benefit_id"], "additionalProperties": False}}},
```

In `_Session.__init__` add `self.proposals: list[dict] = []`. In `run_tool`, before the final `return`:

```python
        if name == "propose_mark":
            state = benefit_state(self.db, args["benefit_id"], self.as_of, self.marks) if args.get("benefit_id") in catalog_by_id() else None
            if state is None or state["tracking"] != "manual":
                return {"error": "only manually tracked credits can be marked"}
            current = state["current"]
            if current["marked"]:
                return {"error": "already marked for this period"}
            proposal = {"benefit_id": state["benefit_id"], "title": state["title"], "period_start": current["start"],
                        "period_label": current["label"], "amount": current["amount_minor"] / 100}
            if all(p["benefit_id"] != proposal["benefit_id"] for p in self.proposals):
                self.proposals.append(proposal)
            return {"proposal": proposal, "note": "Shown to the user as a button. Not marked until they tap it."}
```

(Check that `state["current"]` carries `marked`, `start`, `label`, `amount_minor`; `tracker.py:103-106` builds periods with these keys.)

In `summarize_result`, before the final `return ""`:

```python
    if name == "propose_mark" and isinstance(result, dict):
        p = result["proposal"]
        return f"offered to mark {p['title']} ({p['period_label']}) used; waiting for your tap"
```

Add `"proposals": self.proposals` to the `converse` return dict. Add this rule to both `BENEFIT_SYSTEM` and `WALLET_SYSTEM`:

```
- If the user says they used a manual credit (tracking = manual) this period, call propose_mark and tell them to tap the button to confirm. Never say it is already marked.
```

- [ ] **Step 4: Implement idempotent marks** in `app.py`: add `used: bool | None = None` to `MarkRequest`, and in `mark`, after finding `period`:

```python
            if request.used is not None and period["marked"] == request.used:
                return state  # already in the requested state; a toggle here would undo it
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run --extra ui python -m unittest discover -s tests`
Expected: all PASS.

- [ ] **Step 6: Add one sentence to `AGENTS.md` → Runtime:** "Chat may *propose* a mark with `propose_mark`; only the user's tap writes it." Leave uncommitted.

### Task 8: Multi-step and briefing evals (E, backend)

**Files:**
- Modify: `evals/suites.py` (`check_answer`: `min_tool_calls`, `names_top_at_risk`; `run_chat`: briefing kind, wallet cases without `expect_benefit`)
- Modify: `evals/cases.json` (two chat cases)
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `wallet_briefing` (Task 2).
- Produces: case fields `kind: "briefing"`, `min_tool_calls: int`, computed `top_title`.

- [ ] **Step 1: Write the failing test** (`tests/test_eval_runner.py`)

```python
    def test_min_tool_calls_and_top_at_risk_checks(self):
        reply = {"answer": "- **Walmart+ Monthly Membership Credit**: $12.95 left", "unverified_amounts": [],
                 "tool_trace": [{"tool": "get_benefit_status"}, {"tool": "get_community_tips"}]}
        case = {"checks": ["min_tool_calls", "names_top_at_risk"], "min_tool_calls": 2, "top_title": "Walmart+ Monthly Membership Credit"}
        self.assertEqual(check_answer(case, reply, None), {"min_tool_calls": True, "names_top_at_risk": True})
        case = {"checks": ["min_tool_calls", "names_top_at_risk"], "min_tool_calls": 3, "top_title": "$200 Uber Cash"}
        self.assertEqual(check_answer(case, reply, None), {"min_tool_calls": False, "names_top_at_risk": False})
        case = {"checks": ["names_top_at_risk"], "top_title": ""}  # nothing at risk: nothing to name
        self.assertEqual(check_answer(case, reply, None), {"names_top_at_risk": True})
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra ui python -m unittest tests.test_eval_runner -v`
Expected: FAIL with `ValueError: unknown check: min_tool_calls`

- [ ] **Step 3: Implement the checks** in `check_answer`, before the `else`:

```python
        elif name == "min_tool_calls":
            checks[name] = len(reply["tool_trace"]) >= case["min_tool_calls"]
        elif name == "names_top_at_risk":
            words = [w for w in re.findall(r"[A-Za-z+]{4,}", case["top_title"]) if w.lower() not in _COMMON_TITLE_WORDS]
            checks[name] = not case["top_title"] or any(w.lower() in answer.lower() for w in words)
```

with, near the top of `suites.py` (add `import re`):

```python
# Title words too generic to show the model named the right credit.
_COMMON_TITLE_WORDS = {"credit", "monthly", "membership", "cash", "annual"}
```

- [ ] **Step 4: Extend `run_chat`.** Import `wallet_briefing`. Replace the `if case.get("benefit_id") ... else ...` block with:

```python
        if case.get("kind") == "briefing":
            status = None
            reply = wallet_briefing(db, as_of=as_of, marks=marks, client=client, embedder=embedder)
            at_risk = [b for b in track(db, as_of, marks)["benefits"] if b["current"]["status"] == "at_risk"]
            top = max(at_risk, key=lambda b: b["current"]["remaining_minor"], default=None)
            case = {**case, "top_title": top["title"] if top else ""}
            context: object = [{"title": b["title"], "left": b["current"]["remaining_minor"] / 100,
                                "ends": b["current"]["end"]} for b in at_risk]
        elif case.get("benefit_id"):
            status = compact_status(benefit_state(db, case["benefit_id"], as_of, marks), as_of)
            reply = benefit_chat(db, case["benefit_id"], messages, as_of=as_of, marks=marks,
                                 client=client, embedder=embedder)
            context = status
        else:
            status = None
            reply = wallet_ask(db, messages, as_of=as_of, marks=marks, client=client, embedder=embedder)
            if case.get("expect_benefit"):
                expected = benefit_state(db, case["expect_benefit"], as_of, marks)
                context = {"expected_benefit": expected["title"], "terms": expected["terms"][:600]}
            else:
                context = [compact_status(s, as_of) for s in track(db, as_of, marks)["benefits"]]
```

- [ ] **Step 5: Add the cases** to `evals/cases.json` → `"chat"`:

```json
  {
    "id": "wallet-compare-multi-step",
    "benefit_id": null,
    "question": "Compare my Resy and lululemon credits: which have I used more reliably this year, and one community idea for the weaker one?",
    "expect_tool": "get_benefit_status",
    "min_tool_calls": 2,
    "checks": ["expected_tool", "min_tool_calls", "no_unverified_amounts", "community_labelled"]
  },
  {
    "id": "weekly-briefing",
    "kind": "briefing",
    "benefit_id": null,
    "question": "Write this week's plan.",
    "expect_tool": "get_community_tips",
    "checks": ["expected_tool", "names_top_at_risk", "no_unverified_amounts", "community_labelled"]
  }
```

- [ ] **Step 6: Run to verify**

Run: `uv run --extra ui python -m unittest discover -s tests`
Expected: all PASS. If an existing `run_chat` test feeds a fixed list of fake replies for all chat cases, add replies for the two new cases (briefing: one tool call to `get_community_tips` then an answer; compare: two `get_benefit_status` calls then an answer), plus one judge reply each.

- [ ] **Step 7: Leave uncommitted.** Do **not** run the live eval; the orchestrator asks the user first (Task 12).

### Task 9: Source labels (C, frontend)

**Files:**
- Modify: `web/src/main.tsx` (`App` summary and EXPIRING SOON eyebrow, `Legend`, `Community`)
- Modify: `web/src/theme.css`

**Interfaces:**
- Consumes: `.source` and `.source.ai` (Task 4).
- Produces: `.source.statements`.

- [ ] **Step 1: Statement labels.** In `App`, first child of `<section className="wallet-summary">`:

```tsx
          <div className="provenance"><span className="source statements">FROM YOUR STATEMENTS</span></div>
```

and change the EXPIRING SOON heading to:

```tsx
<h2 className="eyebrow">EXPIRING SOON · {atRisk.length} <span className="source statements">FROM STATEMENTS</span></h2>
```

- [ ] **Step 2: AI label on the blurb.** In `Community`, replace `<p className="blurb">{data.blurb}</p>` with:

```tsx
      {data.blurb && <><span className="source ai">AI SUMMARY OF THE TIPS BELOW</span><p className="blurb">{data.blurb}</p></>}
```

- [ ] **Step 3: One-line explainer** at the end of `Legend`'s returned `<div>`:

```tsx
    <p className="ai-note">Amounts and statuses are computed from your statements. AI writes the weekly plan, answers questions and summarizes community tips, and every dollar amount it writes is checked against your data.</p>
```

- [ ] **Step 4: CSS**

```css
.source.statements{color:#277445;background:#e0efe3}
.provenance{margin:0 0 4px}
.ai-note{flex-basis:100%;margin:10px 0 0;font-size:12px;line-height:1.5;color:#766550}
```

- [ ] **Step 5:** `cd web && npx tsc -b` → exit 0. Leave uncommitted.

### Task 10: Inline ask bar with state-based suggestions (F, frontend)

**Files:**
- Modify: `web/src/main.tsx` (`askSuggestions`, `AskBar`, `App` state, `AskRail` and `Chat` `initialQuestion`; remove the `.ask-float` button)
- Modify: `web/src/theme.css`

**Interfaces:**
- Consumes: `Tracker`, `Chat`, `AskRail`.
- Produces: `askSuggestions(t: Tracker): string[]`; `Chat` prop `initialQuestion?: { text: string; id: number }`; `AskRail` props `initialQuestion`, `onChanged` (Task 11 uses `onChanged`).

- [ ] **Step 1: Suggestions from state** (above `function Legend`):

```tsx
function askSuggestions(t: Tracker): string[] {
  const risk = t.benefits.filter(b => b.current.status === 'at_risk').sort((a, b) => b.current.remaining_minor - a.current.remaining_minor)[0]
  const missed = [...t.benefits].sort((a, b) => b.ytd.missed_minor - a.ytd.missed_minor)[0]
  const manual = t.benefits.find(b => b.tracking === 'manual' && !b.current.marked && b.current.remaining_minor > 0)
  return [
    risk && `How do I use ${risk.title} before ${fmtDate(risk.current.end)}?`,
    missed?.ytd.missed_minor && `Why do I keep missing ${missed.title}, and what would help?`,
    manual && `I used my ${manual.title} this ${PERIOD_UNIT[manual.period]}`,
    'Which credit covers airport security fast lanes?',
  ].filter((s): s is string => !!s)
}
```

- [ ] **Step 2: `AskBar`**

```tsx
function AskBar({ suggestions, onAsk }: { suggestions: string[]; onAsk: (question: string) => void }) {
  const [draft, setDraft] = React.useState('')
  return <section className="ask-bar">
    <form className="chat-form" onSubmit={e => { e.preventDefault(); if (draft.trim()) { onAsk(draft.trim()); setDraft('') } }}>
      <input aria-label="Ask PerkWatch" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Ask PerkWatch about any credit…" maxLength={2000}/>
      <button disabled={!draft.trim()}>Ask</button></form>
    <div className="suggestions">{suggestions.map(s => <button key={s} className="filter-chip" onClick={() => onAsk(s)}>{s}</button>)}</div>
  </section>
}
```

- [ ] **Step 3: Wire `App`.** Add state and a handler:

```tsx
  const [askQuestion, setAskQuestion] = React.useState<{ text: string; id: number } | undefined>()
  const ask = (text: string) => { setAskQuestion({ text, id: Date.now() }); setAskOpen(true) }
```

Render `<AskBar suggestions={askSuggestions(tracker)} onAsk={ask}/>` right after `<Briefing tracker={tracker}/>`. Change the rail to `{askOpen && <AskRail asOf={tracker.as_of} initialQuestion={askQuestion} onChanged={reload} onClose={() => { setAskOpen(false); setAskQuestion(undefined) }}/>}`. Delete the `<button className="ask-float" …>` line.

- [ ] **Step 4: Auto-send in `Chat`.** Add prop `initialQuestion?: { text: string; id: number }` and, after the existing effects:

```tsx
  const sent = React.useRef(0)
  React.useEffect(() => {
    // The ref survives StrictMode's double effect, so each question is sent once.
    if (initialQuestion && sent.current !== initialQuestion.id) { sent.current = initialQuestion.id; send(initialQuestion.text) }
  }, [initialQuestion])
```

`AskRail` takes `initialQuestion` and `onChanged` and passes both to its `Chat`.

- [ ] **Step 5: CSS**

```css
.ask-bar{margin:14px 0 4px}
.ask-bar .chat-form input{background:#fffdf8}
```

- [ ] **Step 6:** `cd web && npx tsc -b` → exit 0. Leave uncommitted.

### Task 11: Proposal buttons (D, frontend)

**Files:**
- Modify: `web/src/main.tsx` (`Proposal` type and component; `Reply.proposals`; `Chat` renders proposals; `BenefitRail` passes `onChanged` and a manual-credit suggestion)
- Modify: `web/src/theme.css`

**Interfaces:**
- Consumes: Phase 2 API contract; `Chat` prop `onChanged` from Task 10.
- Produces: `function ProposalButton({ proposal, asOf, onChanged })`.

- [ ] **Step 1: Types.** Add `type Proposal = { benefit_id: string; title: string; period_start: string; period_label: string; amount: number }` and `proposals?: Proposal[]` to `Reply`.

- [ ] **Step 2: Component** (above `function Chat`):

```tsx
function ProposalButton({ proposal: p, asOf, onChanged }: { proposal: Proposal; asOf: string; onChanged?: () => void }) {
  const [state, setState] = React.useState<'idle' | 'saving' | 'done' | 'error'>('idle')
  async function confirm() {
    setState('saving')
    try {
      // used: true makes this idempotent: a second tap, or a period marked elsewhere, stays marked.
      await api(`/api/benefits/${encodeURIComponent(p.benefit_id)}/mark`, { period_start: p.period_start, as_of: asOf, used: true })
      setState('done'); onChanged?.()
    } catch { setState('error') }
  }
  return <div className="proposal"><span>Agent suggests: mark <b>{p.title}</b> ({p.period_label}) as used · {money(Math.round(p.amount * 100))}</span>
    <button disabled={state === 'saving' || state === 'done'} onClick={confirm}>{state === 'done' ? 'Marked ✓' : state === 'error' ? 'Retry' : 'Mark used'}</button></div>
}
```

- [ ] **Step 3: Render and wire.** `Chat` gains `onChanged?: () => void`; under `AgentTrace` render `{m.reply?.proposals?.map(p => <ProposalButton key={p.benefit_id} proposal={p} asOf={asOf} onChanged={onChanged}/>)}`. `BenefitRail` passes `onChanged={onChanged}` to `Chat`, and for manual credits puts `'I already used this one'` first in `suggestions`.

- [ ] **Step 4: CSS**

```css
.proposal{margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border:1px dashed #5c4bf5;border-radius:12px;background:#f4f2ff;font-size:13px}
.proposal button{border:0;border-radius:10px;background:#5c4bf5;color:#fff;padding:8px 12px;font-weight:700;white-space:nowrap}
.proposal button:disabled{background:#277445}
```

- [ ] **Step 5:** `cd web && npx tsc -b` → exit 0. Leave uncommitted.

### Task 12: Phase 2 integration, evals and hand-off (orchestrator)

- [ ] **Step 1:** Full checks as in Task 6 Step 1 (expect the new totals, all passing).
- [ ] **Step 2: Browser check** on :8001/:5174 with demo data:
  - the ask bar shows state-based chips; clicking one opens the rail and sends it once;
  - "I used my $200 Uber Cash this month" shows `propose_mark → offered to mark …` and a **Mark used** button; tapping it updates the Uber Cash dots and the totals, and a second tap changes nothing (Review Focus 5);
  - the compare question shows 2 or more steps;
  - the labels appear: FROM YOUR STATEMENTS, AI-WRITTEN, AI SUMMARY, and the legend note.
- [ ] **Step 3: Ask the user before the live eval** (about 17 OpenAI calls): `uv run python evals/run.py --suite chat --real`. Record the passed count and mean judge score.
- [ ] **Step 4: Hand off doc updates** to the session that owns `docs/capstone/` (new screenshots, chat eval numbers, the course-concepts W5/W6/W7 lines); update `README.md` and `docs/explanation/perk-watch-v3-benefit-tracker.md` for the briefing endpoint and `propose_mark`.
- [ ] **Step 5:** Ask the user to approve the Phase 2 commit on `v3/benefit-tracker`.

---

**Related, not in scope:** the prompt-injection gap (tips and terms enter prompts as trusted text) grows slightly because the briefing adds tips to one more prompt. The fix (wrap them as data, with a test) fits naturally before Task 12's live eval if the user wants it.
