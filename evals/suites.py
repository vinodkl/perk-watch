"""Eval suites: E1 tracker (no LLM), E2 retrieval recall@3, E3 chat checks + LLM judge, perf (cost/latency)."""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
import time
from datetime import date
from types import SimpleNamespace
from typing import Any

from perk_watch.runtime.chat import MODEL, benefit_chat, compact_status, wallet_ask, wallet_briefing
from perk_watch.runtime.retrieval.search import search_benefits, search_community_ideas
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


def run_community_retrieval(db: sqlite3.Connection, cases: list[dict], embedder: Any, k: int = 3) -> dict:
    """recall@k for community tip/idea search (search_community_ideas), separate from official-terms search."""
    if not cases:
        return {"cases": 0, "hits": 0, f"recall_at_{k}": None, "misses": []}
    hits, misses = 0, []
    for case in cases:
        top = [h["benefit_id"] for h in search_community_ideas(db, case["question"], embedder=embedder, limit=k)]
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
        elif name == "not_tracked":
            lowered = answer.lower()
            checks[name] = any(phrase in lowered for phrase in _NOT_TRACKED_PHRASES)
        else:
            raise ValueError(f"unknown check: {name}")
    return checks


# Phrases accepted as "this isn't one of your tracked credits" for the not_tracked check.
_NOT_TRACKED_PHRASES = [
    "not tracked", "don't track", "doesn't track", "not one of your", "no record",
    "not a credit i track", "not in your wallet", "isn't tracked", "don't have that card",
    "doesn't have that card", "not have that card", "can't find", "cannot find",
    "not a card you have", "not a tracked", "no tracked", "do not have access",
    "don't have access", "doesn't have access", "no specific benefit", "not something i track",
    "not part of your", "not associated with your", "no information about that card",
    "no access to any", "not have any information", "only have access", "you'll need to check",
    "you will need to check", "check its terms", "check your card's terms", "check with your card issuer",
    "not something i have", "i don't have information", "no information on that", "not one i track",
    "not a benefit i have", "unable to find", "i'm not able to find", "not linked to",
    "does not have a", "doesn't have a", "does not track", "isn't one of your", "not one of the",
]


# Default judge model kept for backward compatibility; gpt-4o is recommended for more reliable judging
# (pass --judge-model gpt-4o on the CLI).
JUDGE_MODEL = MODEL


def judge(client: Any, context: object, question: str, answer: str, model: str = JUDGE_MODEL, runs: int = 1) -> dict:
    """Ask the judge model to score the answer, averaging `runs` independent calls.

    A judge call that returns invalid JSON scores None for that run and never raises; the run continues
    and only the valid scores are averaged. If every run is invalid, the overall score is None.
    """
    scores: list[int | None] = []
    reasons: list[str] = []
    for _ in range(max(1, runs)):
        response = client.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": JUDGE % (json.dumps(context, default=str), question, answer)}])
        try:
            verdict = json.loads(response.choices[0].message.content)
            scores.append(int(verdict["score"]))
            reasons.append(str(verdict.get("reason", "")))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            scores.append(None)
            reasons.append("judge returned invalid JSON")
    valid = [s for s in scores if s is not None]
    mean_score = round(sum(valid) / len(valid), 2) if valid else None
    spread = round(max(valid) - min(valid), 2) if len(valid) > 1 else (0.0 if valid else None)
    return {"score": mean_score, "scores": scores, "spread": spread,
            "reason": reasons[0] if reasons else "", "model": model}


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 4) if values else None


def run_chat(db: sqlite3.Connection, cases: list[dict], *, as_of: date, client: Any, embedder: Any = None,
             marks: dict | None = None, judge_model: str = JUDGE_MODEL, judge_runs: int = 1) -> dict:
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
        verdict = judge(client, context, case["question"], reply["answer"], model=judge_model, runs=judge_runs)
        # Usage/latency/cost land in the reply once runtime/chat.py records them; .get() keeps this
        # suite working before and after that lands.
        usage = reply.get("usage") or {}
        results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                        "judge_score": verdict["score"], "judge_scores": verdict["scores"],
                        "judge_spread": verdict["spread"], "judge_reason": verdict["reason"],
                        "tools": [t["tool"] for t in reply["tool_trace"]],
                        "unverified_amounts": reply["unverified_amounts"], "answer": reply["answer"],
                        "usage": reply.get("usage"), "latency_ms": reply.get("latency_ms"),
                        "cost_usd": reply.get("cost_usd")})
    scores = [r["judge_score"] for r in results if r["judge_score"] is not None]
    spreads = [r["judge_spread"] for r in results if r["judge_spread"] is not None]
    prompt_tokens = [r["usage"].get("prompt_tokens") for r in results if r.get("usage")]
    completion_tokens = [r["usage"].get("completion_tokens") for r in results if r.get("usage")]
    model_calls = [r["usage"].get("model_calls") for r in results if r.get("usage")]
    costs = [r["cost_usd"] for r in results if r.get("cost_usd") is not None]
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    return {"cases": len(results), "passed": sum(r["passed"] for r in results),
            "mean_judge_score": round(sum(scores) / len(scores), 2) if scores else None,
            "mean_judge_spread": _mean(spreads), "judge_model": judge_model, "judge_runs": judge_runs,
            "totals": {
                "total_prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
                "total_completion_tokens": sum(completion_tokens) if completion_tokens else None,
                "total_model_calls": sum(model_calls) if model_calls else None,
                "total_cost_usd": round(sum(costs), 5) if costs else None,
                "mean_latency_ms": _mean(latencies),
                "total_latency_ms": sum(latencies) if latencies else None,
                "cases_missing_usage": sum(1 for r in results if not r.get("usage")),
            },
            "results": results}


# ---------- perf (cost + latency) ----------

def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lo, hi = int(rank), min(int(rank) + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _perf_feature(case: dict) -> str:
    if case.get("kind") == "briefing":
        return "briefing"
    return "benefit_chat" if case.get("benefit_id") else "wallet_ask"


def _perf_reply(db: sqlite3.Connection, case: dict, *, as_of: date, client: Any, embedder: Any,
                marks: dict | None) -> dict:
    messages = [{"role": "user", "content": case["question"]}]
    if case.get("kind") == "briefing":
        return wallet_briefing(db, as_of=as_of, marks=marks, client=client, embedder=embedder)
    if case.get("benefit_id"):
        return benefit_chat(db, case["benefit_id"], messages, as_of=as_of, marks=marks,
                            client=client, embedder=embedder)
    return wallet_ask(db, messages, as_of=as_of, marks=marks, client=client, embedder=embedder)


def run_perf(db: sqlite3.Connection, cases: list[dict], *, as_of: date, client: Any, embedder: Any = None,
             marks: dict | None = None, repeats: int = 1) -> dict:
    """Latency and cost per feature (benefit_chat, wallet_ask, briefing) over `repeats` runs of each case.

    No LLM judge here (that would add cost this suite is meant to measure); it only exercises the chat
    functions themselves. Usage/cost fields come from reply.get(...) so this also runs, with missing_usage
    counted, before runtime/chat.py records them.
    """
    by_feature: dict[str, dict[str, list]] = {}
    for case in cases:
        feature = _perf_feature(case)
        stats = by_feature.setdefault(feature, {
            "latency_ms": [], "prompt_tokens": [], "completion_tokens": [], "model_calls": [],
            "cost_usd": [], "requests": 0, "missing_usage": 0})
        for _ in range(max(1, repeats)):
            start = time.perf_counter()
            reply = _perf_reply(db, case, as_of=as_of, client=client, embedder=embedder, marks=marks)
            wall_ms = (time.perf_counter() - start) * 1000
            stats["requests"] += 1
            stats["latency_ms"].append(reply.get("latency_ms") if reply.get("latency_ms") is not None else wall_ms)
            usage = reply.get("usage")
            if usage:
                if usage.get("prompt_tokens") is not None:
                    stats["prompt_tokens"].append(usage["prompt_tokens"])
                if usage.get("completion_tokens") is not None:
                    stats["completion_tokens"].append(usage["completion_tokens"])
                if usage.get("model_calls") is not None:
                    stats["model_calls"].append(usage["model_calls"])
            else:
                stats["missing_usage"] += 1
            if reply.get("cost_usd") is not None:
                stats["cost_usd"].append(reply["cost_usd"])

    report: dict[str, Any] = {}
    all_latency: list[float] = []
    all_cost: list[float] = []
    total_requests = 0
    for feature, stats in by_feature.items():
        lat = stats["latency_ms"]
        all_latency += lat
        all_cost += stats["cost_usd"]
        total_requests += stats["requests"]
        report[feature] = {
            "requests": stats["requests"],
            "p50_latency_ms": round(_percentile(lat, 0.5), 1) if lat else None,
            "p95_latency_ms": round(_percentile(lat, 0.95), 1) if lat else None,
            "mean_prompt_tokens": _mean(stats["prompt_tokens"]),
            "mean_completion_tokens": _mean(stats["completion_tokens"]),
            "mean_model_calls": _mean(stats["model_calls"]),
            "mean_cost_usd": round(_mean(stats["cost_usd"]), 6) if stats["cost_usd"] else None,
            "total_cost_usd": round(sum(stats["cost_usd"]), 6) if stats["cost_usd"] else None,
            "missing_usage": stats["missing_usage"],
        }
    report["totals"] = {
        "requests": total_requests,
        "p50_latency_ms": round(_percentile(all_latency, 0.5), 1) if all_latency else None,
        "p95_latency_ms": round(_percentile(all_latency, 0.95), 1) if all_latency else None,
        "total_cost_usd": round(sum(all_cost), 6) if all_cost else None,
    }
    return report


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
