from __future__ import annotations

import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
from harness import PlannedAgentClient, factual_checks, run_case, tool_plan
from fixture import FixtureEmbedder, open_fixture


class EvaluationRunnerTests(unittest.TestCase):
    def test_factual_check_uses_structured_fields_not_answer_wording(self):
        expected = {
            "tool_results": {"evaluate_benefits": {"remaining_amount_minor": 8000}},
            "required_source_ids": ["terms-1"],
            "transaction_ids": ["tx-1"],
        }
        results = [
            {"tool": "evaluate_benefits", "result": {"remaining_amount_minor": 8000}},
            {"tool": "search_benefits", "result": [{"source_reference": {"source_id": "terms-1"}}]},
            {"tool": "get_transaction_evidence", "result": [{"transaction_id": "tx-1"}]},
        ]
        visible = "Paraphrased amount wording.\\n\\n" + "\\n\\n".join(
            json.dumps(row, ensure_ascii=False, indent=2) for call in results
            for row in (call["result"] if isinstance(call["result"], list) else [call["result"]]))
        self.assertEqual(factual_checks(expected, results, visible), [])
        self.assertTrue(factual_checks(expected, results, "The answer omitted the amount."))
        results[0]["result"]["remaining_amount_minor"] = 7000
        self.assertIn("evaluate_benefits: expected structured result not returned",
                      factual_checks(expected, results, "Actually, 8000 remains."))

    def test_case_runs_through_stored_vectors_without_external_calls(self):
        case = {"id": "fixture", "question": "travel credit", "search_question": "travel credit",
                "relevant_benefit_ids": ["fixture:travel-credit"],
                "expected": {"tool_results": {"evaluate_benefits": {"benefit_id": "fixture:travel-credit"}}}}
        usage = {"calls": 0, "tokens": 0, "failures": 0, "retries": 0}
        db = open_fixture()
        try:
            with patch("harness.reword", side_effect=lambda _client, _model, question, _usage: question), \
                 patch("harness.judge", return_value={"clarity": 5}), \
                 patch("harness.rerank", side_effect=lambda _client, _model, _question, rows, _usage: rows):
                result = run_case(db, case, client=PlannedAgentClient(tool_plan(case)),
                                  embedder=FixtureEmbedder(), model="fixture", api_usage=usage)
            self.assertEqual(result["fixture_check_failures"], [])
            self.assertEqual(result["live_agent_failures"], [])
            self.assertTrue(result["search"]["basic_hit_at_5"])
        finally:
            db.close()

    def test_plan_passes_explicit_period_and_transaction_expectations(self):
        case = {"question": "credit", "expected": {
            "answer_fields": {"as_of": "2026-10-15", "account_year_start": "2026-04-01"},
            "tool_results": {"evaluate_benefits": {"benefit_id": "fixture:annual"}},
            "transaction_ids": ["tx-1"]}}
        self.assertEqual(tool_plan(case), [
            {"tool": "search_benefits", "arguments": {"question": "credit"}},
            {"tool": "evaluate_benefits", "arguments": {
                "benefit_id": "fixture:annual", "as_of": "2026-10-15",
                "account_year_start": "2026-04-01"}},
            {"tool": "get_transaction_evidence", "arguments": {"transaction_ids": ["tx-1"]}},
        ])


if __name__ == "__main__":
    unittest.main()
