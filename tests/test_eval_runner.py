from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
from run import factual_checks, tool_plan


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
