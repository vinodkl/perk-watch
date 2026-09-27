"""PROTOTYPE (throwaway): three small evals for the tracker prototype.

E1 tracker   : period status + $ vs a MaxRewards answer key (local file, never committed). No LLM.
E2 retrieval : recall@3 of the right benefit for plain-language questions (existing embeddings).
E3 chat      : at-risk chat answers checked in code (amounts, deadline, grounding) + LLM judge 1-5.

Run:  uv run --extra ui python prototype/eval_proto.py [--skip-llm]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracker_proto import DATA_DIR, open_db, track  # noqa: E402

KEY_PATH = DATA_DIR / "prototype" / "maxrewards_answer_key.json"


def e1_tracker() -> dict:
    key = json.loads(KEY_PATH.read_text())
    result = track(open_db(), date.fromisoformat(key["as_of"]))
    ours = {(b["benefit_id"], p["label"]): p for b in result["benefits"] for p in b["periods"]}
    rows, status_ok, amount_ok = [], 0, 0
    for expected in key["periods"]:
        got = ours.get((expected["benefit_id"], expected["label"]))
        got_status = "missing" if got is None else ("current" if got["status"] in {"open", "at_risk"} else got["status"])
        got_used = None if got is None else got["used_minor"] / 100
        s_ok = got_status == expected["status"] or (expected["status"] == "current" and got_status == "used")
        a_ok = got_used is not None and abs(got_used - expected["used"]) < 0.005
        status_ok += s_ok
        amount_ok += a_ok
        if not (s_ok and a_ok):
            rows.append({"benefit": expected["benefit_id"], "period": expected["label"],
                         "expected": [expected["status"], expected["used"]], "got": [got_status, got_used]})
    total = len(key["periods"])
    return {"periods": total, "status_accuracy": round(status_ok / total, 3),
            "amount_accuracy": round(amount_ok / total, 3), "mismatches": rows}


RETRIEVAL_CASES = [
    ("I pay for Disney+ and Hulu, is there a credit for that?", "amex_platinum_300_digital_entertainment_credit"),
    ("Do I get anything back for a Walmart membership?", "amex_platinum_walmart_monthly_membership_credit"),
    ("Is there a quarterly restaurant dining credit?", "amex_platinum_400_resy_credit"),
    ("Which benefit covers fast lane airport security membership?", "amex_platinum_219_clear_credit"),
    ("Can I get my checked bag fees reimbursed?", "amex_platinum_200_airline_fee_credit"),
    ("Is there a credit for athletic clothing?", "amex_platinum_300_lululemon_credit"),
    ("Does my Sapphire card give money back on hotels booked through the bank's travel site?", "chase_sapphire_preferred_benefit_010"),
    ("Is my gym membership covered?", "amex_platinum_300_equinox_credit"),
]


def e2_retrieval() -> dict:
    from app_proto import client, db  # noqa: PLC0415 - needs the API key
    from perk_watch.embeddings import OpenAIEmbeddingProvider
    from perk_watch.runtime.retrieval.search import search_benefits
    embedder = OpenAIEmbeddingProvider(client())
    hits, misses = 0, []
    for question, expected in RETRIEVAL_CASES:
        top = [h["benefit_id"] for h in search_benefits(db, question, embedder=embedder, limit=3)]
        if expected in top:
            hits += 1
        else:
            misses.append({"question": question, "expected": expected, "top3": top})
    return {"cases": len(RETRIEVAL_CASES), "recall_at_3": round(hits / len(RETRIEVAL_CASES), 3), "misses": misses}


CHAT_CASES = [
    ("amex_platinum_400_resy_credit", "How can I use what is left before it resets?"),
    ("amex_platinum_walmart_monthly_membership_credit", "I keep missing this. Is it worth it for me?"),
    ("amex_platinum_200_uber_cash", "What should I do with this before the month ends?"),
]

JUDGE = """Rate this assistant answer from 1 to 5 for how USEFUL and ACTIONABLE it is for a cardholder
trying to use this benefit before it expires (5 = specific, correct-sounding, prioritized; 1 = generic or off-topic).
Return only JSON: {"score": <1-5>, "reason": "<one sentence>"}.
BENEFIT STATUS: %s
QUESTION: %s
ANSWER: %s"""


def e3_chat() -> dict:
    from app_proto import MODEL, benefit_state, chat, client, compact_status  # noqa: PLC0415
    results = []
    for benefit_id, question in CHAT_CASES:
        status = compact_status(benefit_state(benefit_id))
        current = status["current_period"]
        reply = chat(benefit_id, [{"role": "user", "content": question}])
        answer = reply["answer"]
        remaining = f"${current['remaining']:.2f}".replace(".00", "")
        checks = {
            "states_remaining_amount": remaining in answer or f"${current['remaining']:.2f}" in answer,
            "states_deadline": str(current["days_left"]) in answer or "September 30" in answer or "Sep 30" in answer
                               or current["ends"] in answer,
            "no_unverified_amounts": not reply["unverified_amounts"],
            "community_labeled": ("reddit.com" not in answer and "http" not in answer) or "ommunity" in answer,
        }
        judged = client().chat.completions.create(
            model=MODEL, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": JUDGE % (json.dumps(current), question, answer)}])
        verdict = json.loads(judged.choices[0].message.content)
        results.append({"benefit": benefit_id, "checks": checks, "passed": all(checks.values()),
                        "judge_score": verdict.get("score"), "judge_reason": verdict.get("reason"),
                        "tools": [t["tool"] for t in reply["tool_trace"]],
                        "unverified_amounts": reply["unverified_amounts"], "answer": answer})
    return {"cases": len(results), "passed": sum(r["passed"] for r in results),
            "mean_judge_score": round(sum(r["judge_score"] or 0 for r in results) / len(results), 2),
            "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm", action="store_true", help="run only E1 (no API calls)")
    args = parser.parse_args()
    report = {"e1_tracker": e1_tracker()}
    if not args.skip_llm:
        report["e2_retrieval"] = e2_retrieval()
        report["e3_chat"] = e3_chat()
    print(json.dumps(report, indent=2))
