from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))
import run
from fixture import FixtureEmbedder, build_fixture
from suites import check_answer, run_answer_key, run_chat, run_retrieval

AS_OF = date(2026, 9, 26)


def _message(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool_call(name, **args):
    return SimpleNamespace(id=f"call-{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Replays scripted chat replies; no network."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


class ChatSuiteTest(unittest.TestCase):
    def setUp(self):
        self.db = build_fixture()
        self.cases = {c["id"]: c for c in run.CASES["chat"]}

    def tearDown(self):
        self.db.close()

    def test_wallet_case_runs_search_terms_and_passes_checks(self):
        client = FakeClient([
            _message(tool_calls=[_tool_call("search_terms", query="airport security fast lane")]),
            _message("The $219 CLEAR+ Credit covers airport security fast lanes; it runs to Dec 31."),
            _message('{"score": 5, "reason": "Names the right credit."}')])
        report = run_chat(self.db, [self.cases["wallet-clear-lookup"]], as_of=AS_OF,
                          client=client, embedder=FixtureEmbedder())
        result = report["results"][0]
        self.assertEqual(result["checks"], {"expected_tool": True, "names_benefit": True,
                                            "no_unverified_amounts": True, "community_labelled": True})
        self.assertEqual((report["passed"], report["mean_judge_score"]), (1, 5.0))
        search_result = client.requests[1]["messages"][-1]["content"]
        self.assertIn("amex_platinum_219_clear_credit", search_result)
        self.assertEqual(client.requests[2]["response_format"], {"type": "json_object"})

    def test_benefit_case_flags_wrong_amount_deadline_and_bad_judge_json(self):
        client = FakeClient([_message("Spend $250 at a Resy restaurant soon: https://example.test/x"),
                             _message("not json")])
        report = run_chat(self.db, [self.cases["resy-use-before-reset"]], as_of=AS_OF,
                          client=client, embedder=FixtureEmbedder())
        result = report["results"][0]
        self.assertEqual(result["checks"], {"remaining_amount": False, "deadline": False,
                                            "no_unverified_amounts": False, "community_labelled": False})
        self.assertEqual(result["unverified_amounts"], ["$250"])
        self.assertIsNone(report["mean_judge_score"])

    def test_remaining_and_deadline_accept_common_formats(self):
        case = {"checks": ["remaining_amount", "deadline"]}
        status = {"current_period": {"remaining": 100.0, "ends": "2026-09-30", "days_left": 5}}
        for answer in ["You have $100 left until September 30.", "$100.00 left, 5 days to go",
                       "$100 remains through 2026-09-30"]:
            reply = {"answer": answer, "unverified_amounts": [], "tool_trace": []}
            self.assertEqual(check_answer(case, reply, status), {"remaining_amount": True, "deadline": True}, answer)


class RetrievalAndKeyTest(unittest.TestCase):
    def test_retrieval_recall_counts_hits_and_misses(self):
        db = build_fixture()
        cases = [{"question": "airport security fast lane", "benefit_id": "amex_platinum_219_clear_credit"},
                 {"question": "gym equinox", "benefit_id": "amex_platinum_400_resy_credit"}]
        report = run_retrieval(db, cases, FixtureEmbedder())
        self.assertEqual((report["hits"], report["recall_at_3"]), (1, 0.5))
        self.assertEqual(report["misses"][0]["expected"], "amex_platinum_400_resy_credit")

    def test_answer_key_maps_open_and_used_current_periods(self):
        db = build_fixture()
        key = {"as_of": "2026-09-26", "periods": [
            {"benefit_id": "amex_platinum_400_resy_credit", "label": "Q3", "status": "current", "used": 0},
            {"benefit_id": "amex_platinum_300_lululemon_credit", "label": "Q3", "status": "current", "used": 75},
            {"benefit_id": "amex_platinum_400_resy_credit", "label": "Q2", "status": "partial", "used": 50},
            {"benefit_id": "amex_platinum_400_resy_credit", "label": "Q1", "status": "missed", "used": 0}]}
        report = run_answer_key(db, key)
        self.assertEqual(report["matched"], 3)
        self.assertEqual(report["mismatches"][0]["got"], ["used", 100.0])


class RunnerTest(unittest.TestCase):
    def test_tracker_suite_prints_json_without_network(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = run.main(["--suite", "tracker"])
        report = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["e1_tracker"]["synthetic"]["mismatches"], [])
        self.assertNotIn("real", report["e1_tracker"])

    def test_llm_suites_skip_clearly_without_key_or_real_data(self):
        with patch.object(run, "openai_client", return_value=None):
            out = io.StringIO()
            with redirect_stdout(out):
                run.main(["--suite", "all"])
        report = json.loads(out.getvalue())
        self.assertIn("--real", report["e2_retrieval"]["skipped"])
        self.assertIn("OPENAI_API_KEY", report["e3_chat"]["skipped"])


if __name__ == "__main__":
    unittest.main()
