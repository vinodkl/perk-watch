"""Eval-suite coverage that doesn't belong in test_eval_runner.py or test_eval_fixture.py:
perf (cost/latency), judge averaging, tool-budget exhaustion, the unknown-benefit-id error path,
the not-tracked-card chat check, and community-tip retrieval (recall@3 needs --real; this file only
covers the synthetic-fixture path with a fake embedder).
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from fixture import FixtureEmbedder, build_fixture  # noqa: E402
from suites import check_answer, judge, run_community_retrieval, run_perf  # noqa: E402

from perk_watch.runtime.chat import MAX_TOOL_CALLS, _Session  # noqa: E402
from perk_watch.runtime.retrieval.search import search_community_ideas  # noqa: E402

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 9, 26)


def _message(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool_call(name, call_id=None, **args):
    return SimpleNamespace(id=call_id or f"call-{name}-{id(args)}",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Replays scripted chat replies in order; no network."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


# ---------- (b) unknown benefit id ----------

class UnknownBenefitIdTest(unittest.TestCase):
    def test_get_benefit_status_returns_error_dict_instead_of_raising(self):
        db = build_fixture()
        try:
            session = _Session(db, AS_OF, {}, client=FakeClient([]), embedder=FixtureEmbedder(), model="test")
            result = session.run_tool("get_benefit_status", {"benefit_id": "not_a_real_benefit"})
            self.assertIn("error", result)
            self.assertIn("not a tracked benefit", result["error"])
        finally:
            db.close()

    def test_unknown_benefit_id_error_is_returned_to_the_model_not_raised(self):
        # The model calls get_benefit_status with a bogus id, gets the error dict as a tool result,
        # and still produces a final answer -- the session never raises for this.
        db = build_fixture()
        try:
            client = FakeClient([
                _message(tool_calls=[_tool_call("get_benefit_status", benefit_id="does_not_exist")]),
                _message("I couldn't find that credit."),
            ])
            session = _Session(db, AS_OF, {}, client=client, embedder=FixtureEmbedder(), model="test")
            reply = session.converse("system", "WALLET CONTEXT:\n[]", [{"role": "user", "content": "hi"}])
            self.assertEqual(reply["answer"], "I couldn't find that credit.")
            self.assertEqual(len(reply["tool_trace"]), 1)
            self.assertIn("error", reply["tool_trace"][0]["summary"])
            # The tool result that went back to the model is an error dict, not a raised exception.
            tool_message = client.requests[1]["messages"][-1]
            self.assertEqual(tool_message["role"], "tool")
            self.assertIn("error", tool_message["content"])
        finally:
            db.close()


# ---------- (c) tool budget exhaustion ----------

class ToolBudgetTest(unittest.TestCase):
    def test_budget_exhaustion_ends_the_loop_with_a_final_answer_and_a_skip_trace(self):
        db = build_fixture()
        try:
            # A rogue model keeps requesting tools past MAX_TOOL_CALLS; the (MAX_TOOL_CALLS + 1)-th
            # request must be skipped for budget, and the model is expected to then produce a final answer.
            tool_replies = [_message(tool_calls=[_tool_call("search_terms", query="streaming")])
                            for _ in range(MAX_TOOL_CALLS + 1)]
            final_reply = _message("Here is what I found, given what I could look up.")
            client = FakeClient(tool_replies + [final_reply])
            session = _Session(db, AS_OF, {}, client=client, embedder=FixtureEmbedder(), model="test")
            reply = session.converse("system", "WALLET CONTEXT:\n[]", [{"role": "user", "content": "hi"}])

            self.assertEqual(reply["answer"], "Here is what I found, given what I could look up.")
            self.assertEqual(len(reply["tool_trace"]), MAX_TOOL_CALLS + 1)
            # The first MAX_TOOL_CALLS ran for real; the one past budget is skipped.
            for entry in reply["tool_trace"][:MAX_TOOL_CALLS]:
                self.assertNotEqual(entry["summary"], "skipped: tool budget spent")
            self.assertEqual(reply["tool_trace"][MAX_TOOL_CALLS]["summary"], "skipped: tool budget spent")
        finally:
            db.close()


# ---------- (a) not-tracked-card check ----------

class NotTrackedCheckTest(unittest.TestCase):
    def test_not_tracked_check_accepts_common_phrasings(self):
        case = {"checks": ["not_tracked"]}
        for answer in ["That's not tracked in your wallet.", "I don't track a Citi Double Cash card for you.",
                       "That's not one of your tracked cards.", "I couldn't find that credit -- no record of it.",
                       "I do not have access to any specific benefits related to that card in the current context."]:
            reply = {"answer": answer, "unverified_amounts": [], "tool_trace": []}
            self.assertEqual(check_answer(case, reply, None), {"not_tracked": True}, answer)

    def test_not_tracked_check_rejects_answers_that_invent_a_credit(self):
        case = {"checks": ["not_tracked"]}
        reply = {"answer": "Yes, use the $300 travel credit before it expires.", "unverified_amounts": ["$300"],
                 "tool_trace": []}
        self.assertEqual(check_answer(case, reply, None), {"not_tracked": False})

    def test_untracked_card_case_is_registered_in_cases_json(self):
        case = next(c for c in CASES["chat"] if c["id"] == "wallet-untracked-card")
        self.assertIn("no_unverified_amounts", case["checks"])
        self.assertIn("not_tracked", case["checks"])
        self.assertIsNone(case["benefit_id"])


# ---------- (d) judge invalid JSON, averaged over multiple runs ----------

class JudgeAveragingTest(unittest.TestCase):
    def test_judge_averages_valid_scores_and_ignores_invalid_ones(self):
        client = FakeClient([
            _message('{"score": 4, "reason": "solid"}'),
            _message("not json at all"),
            _message('{"score": 2, "reason": "meh"}'),
        ])
        verdict = judge(client, {"ctx": 1}, "question", "answer", model="gpt-4o", runs=3)
        self.assertEqual(verdict["score"], 3.0)  # mean of the two valid scores (4, 2)
        self.assertEqual(verdict["scores"], [4, None, 2])
        self.assertEqual(verdict["model"], "gpt-4o")
        self.assertEqual(verdict["spread"], 2.0)
        self.assertEqual(len(client.requests), 3)  # the loop continued past the invalid run

    def test_judge_all_invalid_returns_none_and_does_not_raise(self):
        client = FakeClient([_message("nope"), _message("still nope")])
        verdict = judge(client, {}, "q", "a", runs=2)
        self.assertIsNone(verdict["score"])
        self.assertIsNone(verdict["spread"])
        self.assertEqual(verdict["scores"], [None, None])

    def test_judge_default_runs_is_one_and_backward_compatible(self):
        client = FakeClient([_message('{"score": 5, "reason": "great"}')])
        verdict = judge(client, {}, "q", "a")
        self.assertEqual(verdict["score"], 5)
        self.assertEqual(verdict["scores"], [5])
        self.assertEqual(verdict["spread"], 0.0)


# ---------- perf suite ----------

class PerfSuiteTest(unittest.TestCase):
    def test_perf_suite_groups_by_feature_and_reports_percentiles(self):
        db = build_fixture()
        try:
            cases = CASES["perf"]
            # One scripted final-answer reply per request (no tool calls, no judge calls).
            replies = [_message("A short synthetic answer.") for _ in cases]
            client = FakeClient(replies)
            report = run_perf(db, cases, as_of=AS_OF, client=client, embedder=FixtureEmbedder(), repeats=1)
            self.assertEqual(set(report) - {"totals"}, {"benefit_chat", "wallet_ask", "briefing"})
            self.assertEqual(report["benefit_chat"]["requests"], 3)
            self.assertEqual(report["wallet_ask"]["requests"], 3)
            self.assertEqual(report["briefing"]["requests"], 1)
            self.assertEqual(report["totals"]["requests"], 7)
            self.assertIsNotNone(report["benefit_chat"]["p50_latency_ms"])
            self.assertIsNotNone(report["benefit_chat"]["p95_latency_ms"])
            # Every chat reply carries usage now, so nothing is counted as missing.
            self.assertEqual(report["benefit_chat"]["missing_usage"], 0)
            self.assertEqual(report["benefit_chat"]["mean_model_calls"], 1)
        finally:
            db.close()

    def test_perf_suite_repeats_each_case(self):
        db = build_fixture()
        try:
            cases = [c for c in CASES["perf"] if c["id"] == "perf-resy"]
            replies = [_message("Answer one."), _message("Answer two."), _message("Answer three.")]
            client = FakeClient(replies)
            report = run_perf(db, cases, as_of=AS_OF, client=client, embedder=FixtureEmbedder(), repeats=3)
            self.assertEqual(report["benefit_chat"]["requests"], 3)
            self.assertEqual(report["totals"]["requests"], 3)
        finally:
            db.close()

    def test_perf_suite_uses_usage_and_cost_fields_when_present(self):
        # Simulates the reply shape once runtime/chat.py records usage/latency/cost: run_perf must
        # read them via .get() rather than recomputing wall-clock latency or skipping cost.
        db = build_fixture()
        try:
            case = next(c for c in CASES["perf"] if c["id"] == "perf-resy")

            class RichClient(FakeClient):
                pass

            client = RichClient([_message("Answer.")])

            import suites as suites_module

            def fake_benefit_chat(*args, **kwargs):
                return {"answer": "Answer.", "tool_trace": [], "unverified_amounts": [],
                        "usage": {"model_calls": 1, "prompt_tokens": 100, "completion_tokens": 20,
                                 "total_tokens": 120},
                        "latency_ms": 250, "cost_usd": 0.001}

            original = suites_module.benefit_chat
            suites_module.benefit_chat = fake_benefit_chat
            try:
                report = run_perf(db, [case], as_of=AS_OF, client=client, embedder=FixtureEmbedder(), repeats=1)
            finally:
                suites_module.benefit_chat = original
            entry = report["benefit_chat"]
            self.assertEqual(entry["missing_usage"], 0)
            self.assertEqual(entry["mean_prompt_tokens"], 100)
            self.assertEqual(entry["mean_completion_tokens"], 20)
            self.assertEqual(entry["mean_model_calls"], 1)
            self.assertEqual(entry["mean_cost_usd"], 0.001)
            self.assertEqual(entry["p50_latency_ms"], 250)
        finally:
            db.close()


# ---------- community retrieval (synthetic fixture path) ----------

class CommunityRetrievalFixtureTest(unittest.TestCase):
    """The real recall@3 community cases in cases.json need --real (see run.py); this exercises the
    same search_community_ideas path against the synthetic fixture's community tips/ideas."""

    def test_search_community_ideas_finds_the_equinox_tip_on_the_fixture(self):
        db = build_fixture()
        try:
            hits = search_community_ideas(db, "front desk trick to make the Equinox gym credit apply",
                                          embedder=FixtureEmbedder(), limit=3)
            self.assertIn("amex_platinum_300_equinox_credit", [h["benefit_id"] for h in hits])
        finally:
            db.close()

    def test_run_community_retrieval_reports_hits_and_misses_on_the_fixture(self):
        db = build_fixture()
        try:
            cases = [
                {"question": "gift card trick to use up the Resy credit", "benefit_id": "amex_platinum_400_resy_credit"},
                {"question": "totally unrelated made-up benefit", "benefit_id": "amex_platinum_219_clear_credit"},
            ]
            report = run_community_retrieval(db, cases, FixtureEmbedder(), k=3)
            self.assertEqual(report["cases"], 2)
            self.assertGreaterEqual(report["hits"], 1)
            self.assertEqual(len(report["misses"]) + report["hits"], 2)
        finally:
            db.close()

    def test_empty_case_list_reports_none_recall_without_dividing_by_zero(self):
        db = build_fixture()
        try:
            report = run_community_retrieval(db, [], FixtureEmbedder())
            self.assertEqual(report, {"cases": 0, "hits": 0, "recall_at_3": None, "misses": []})
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
