"""Three eval suites: E1 tracker (no LLM), E2 retrieval recall@3, E3 chat checks + LLM judge."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from types import SimpleNamespace
from typing import Any

from perk_watch.runtime.chat import MODEL, benefit_chat, compact_status, wallet_ask, wallet_briefing
from perk_watch.runtime.retrieval.search import search_benefits
from perk_watch.runtime.tracker import benefit_state, track

# Title words too generic to show the model named the right credit.
_COMMON_TITLE_WORDS = {"credit", "monthly", "membership", "cash", "annual"}


# ---------- E1 tracker ----------

def run_tracker(db: sqlite3.Connection, scenarios: list[dict]) -> dict:
    """Compare tracker periods and totals with hand-computed expectations for the synthetic wallet."""
    checked = status_ok = amount_ok = 0
    mismatches = []
    for scenario in scenarios:
        marks = {(b, start): minor for b, start, minor in scenario.get("marks", [])}
        result = track(db, date.fromisoformat(scenario["as_of"]), marks)
        ours = {(b["benefit_id"], p["label"]): p for b in result["benefits"] for p in b["periods"]}
        for expected in scenario["periods"]:
            got = ours.get((expected["benefit_id"], expected["period"]), {})
            s_ok = got.get("status") == expected["status"]
            a_ok = got.get("used_minor") == expected["used_minor"] and (
                "amount_minor" not in expected or got.get("amount_minor") == expected["amount_minor"])
            checked, status_ok, amount_ok = checked + 1, status_ok + s_ok, amount_ok + a_ok
            if not (s_ok and a_ok):
                mismatches.append({"scenario": scenario["name"], "benefit": expected["benefit_id"],
                                   "period": expected["period"],
                                   "expected": [expected["status"], expected["used_minor"], expected.get("amount_minor")],
                                   "got": [got.get("status"), got.get("used_minor"), got.get("amount_minor")]})
        for name, value in scenario.get("totals", {}).items():
            if result["totals"][name] != value:
                mismatches.append({"scenario": scenario["name"], "total": name,
                                   "expected": value, "got": result["totals"][name]})
        if "unmatched_credit_lines" in scenario and result["unmatched_credit_lines"] != scenario["unmatched_credit_lines"]:
            mismatches.append({"scenario": scenario["name"], "total": "unmatched_credit_lines",
                               "expected": scenario["unmatched_credit_lines"], "got": result["unmatched_credit_lines"]})
    return {"periods": checked, "status_accuracy": round(status_ok / checked, 3),
            "amount_accuracy": round(amount_ok / checked, 3), "mismatches": mismatches}


def run_answer_key(db: sqlite3.Connection, key: dict) -> dict:
    """Compare against a local MaxRewards answer key (statuses: used/partial/missed/current)."""
    result = track(db, date.fromisoformat(key["as_of"]))
    ours = {(b["benefit_id"], p["label"]): p for b in result["benefits"] for p in b["periods"]}
    status_ok = amount_ok = 0
    mismatches = []
    for expected in key["periods"]:
        got = ours.get((expected["benefit_id"], expected["label"]))
        got_status = "missing" if got is None else ("current" if got["status"] in {"open", "at_risk"} else got["status"])
        got_used = None if got is None else got["used_minor"] / 100
        # MaxRewards shows a used-up current period as "current"; we call it "used".
        s_ok = got_status == expected["status"] or (expected["status"] == "current" and got_status == "used")
        a_ok = got_used is not None and abs(got_used - expected["used"]) < 0.005
        status_ok, amount_ok = status_ok + s_ok, amount_ok + a_ok
        if not (s_ok and a_ok):
            mismatches.append({"benefit": expected["benefit_id"], "period": expected["label"],
                               "expected": [expected["status"], expected["used"]], "got": [got_status, got_used]})
    total = len(key["periods"])
    return {"periods": total, "matched": total - len(mismatches), "status_accuracy": round(status_ok / total, 3),
            "amount_accuracy": round(amount_ok / total, 3), "mismatches": mismatches}


# ---------- E2 retrieval ----------

def run_retrieval(db: sqlite3.Connection, cases: list[dict], embedder: Any, k: int = 3) -> dict:
    hits, misses = 0, []
    for case in cases:
        top = [h["benefit_id"] for h in search_benefits(db, case["question"], embedder=embedder, limit=k)]
        if case["benefit_id"] in top:
            hits += 1
        else:
            misses.append({"question": case["question"], "expected": case["benefit_id"], f"top{k}": top})
    return {"cases": len(cases), "hits": hits, f"recall_at_{k}": round(hits / len(cases), 3), "misses": misses}


# ---------- E3 chat ----------

JUDGE = """Rate this assistant answer from 1 to 5 for how USEFUL and ACTIONABLE it is for a cardholder
(5 = specific, grounded in the context, prioritized; 1 = generic, wrong or off-topic).
Return only JSON: {"score": <1-5>, "reason": "<one sentence>"}.
CONTEXT: %s
QUESTION: %s
ANSWER: %s"""


def _money_forms(value: float) -> list[str]:
    forms = [f"${value:,.2f}", f"${value:.2f}"]
    if value == int(value):
        forms += [f"${value:,.0f}", f"${value:.0f}"]
    return forms


def _deadline_forms(end: str, days_left: int) -> list[str]:
    day = date.fromisoformat(end)
    return [end, f"{day:%B} {day.day}", f"{day:%b} {day.day}", f"{day:%b}. {day.day}",
            f"{days_left} day", f"{day.month}/{day.day}"]


def check_answer(case: dict, reply: dict, status: dict | None) -> dict[str, bool]:
    answer = reply["answer"]
    checks: dict[str, bool] = {}
    for name in case["checks"]:
        if name == "remaining_amount":
            checks[name] = any(f in answer for f in _money_forms(status["current_period"]["remaining"]))
        elif name == "deadline":
            current = status["current_period"]
            checks[name] = any(f in answer for f in _deadline_forms(current["ends"], current["days_left"]))
        elif name == "no_unverified_amounts":
            checks[name] = not reply["unverified_amounts"]
        elif name == "community_labelled":
            links = "http" in answer or "reddit" in answer.lower()
            checks[name] = not links or "ommunity" in answer
        elif name == "expected_tool":
            checks[name] = case["expect_tool"] in [t["tool"] for t in reply["tool_trace"]]
        elif name == "names_benefit":
            checks[name] = case["expect_mention"] in answer
        elif name == "min_tool_calls":
            checks[name] = len(reply["tool_trace"]) >= case["min_tool_calls"]
        elif name == "names_top_at_risk":
            words = [w for w in re.findall(r"[A-Za-z+]{4,}", case["top_title"]) if w.lower() not in _COMMON_TITLE_WORDS]
            checks[name] = not case["top_title"] or any(w.lower() in answer.lower() for w in words)
        else:
            raise ValueError(f"unknown check: {name}")
    return checks


def judge(client: Any, context: object, question: str, answer: str, model: str = MODEL) -> dict:
    response = client.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": JUDGE % (json.dumps(context, default=str), question, answer)}])
    try:
        verdict = json.loads(response.choices[0].message.content)
        return {"score": int(verdict["score"]), "reason": str(verdict.get("reason", ""))}
    except (ValueError, KeyError, TypeError):
        return {"score": None, "reason": "judge returned invalid JSON"}


def run_chat(db: sqlite3.Connection, cases: list[dict], *, as_of: date, client: Any, embedder: Any = None,
             marks: dict | None = None) -> dict:
    results = []
    for case in cases:
        messages = [{"role": "user", "content": case["question"]}]
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
        checks = check_answer(case, reply, status)
        verdict = judge(client, context, case["question"], reply["answer"])
        results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                        "judge_score": verdict["score"], "judge_reason": verdict["reason"],
                        "tools": [t["tool"] for t in reply["tool_trace"]],
                        "unverified_amounts": reply["unverified_amounts"], "answer": reply["answer"]})
    scores = [r["judge_score"] for r in results if r["judge_score"] is not None]
    return {"cases": len(results), "passed": sum(r["passed"] for r in results),
            "mean_judge_score": round(sum(scores) / len(scores), 2) if scores else None, "results": results}


class CountingClient:
    """Wraps an OpenAI client and counts chat and embedding calls, to keep a full run small."""

    def __init__(self, client: Any):
        self._client, self.calls = client, {"chat": 0, "embeddings": 0}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kwargs):
        self.calls["chat"] += 1
        return self._client.chat.completions.create(**kwargs)

    def _embed(self, **kwargs):
        self.calls["embeddings"] += 1
        return self._client.embeddings.create(**kwargs)
