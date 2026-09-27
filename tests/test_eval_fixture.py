from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fixture import FixtureEmbedder, open_fixture
from perk_watch.runtime.calculations import calculate_benefit
from perk_watch.runtime.agent import answer_with_db
from harness import PlannedAgentClient, factual_checks, tool_plan


class EvaluationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.db = open_fixture()

    def tearDown(self):
        self.db.close()

    def test_refund_and_period_boundaries_match_cases(self):
        monthly = calculate_benefit(self.db, "fixture:monthly-credit", as_of="2026-10-15")
        self.assertEqual(monthly["used_amount_minor"], 0)
        self.assertEqual(monthly["remaining_amount_minor"], 5000)
        self.assertEqual(monthly["deadline"], "2026-10-31")
        self.assertEqual(monthly["supporting_transaction_ids"], ["fixture:purchase", "fixture:refund"])
        quarter = calculate_benefit(self.db, "fixture:quarterly-credit", as_of="2026-10-15")
        self.assertEqual(quarter["deadline"], "2026-12-31")
        account = calculate_benefit(self.db, "fixture:account-year-credit", as_of="2026-10-15",
                                    account_year_start="2026-04-01")
        self.assertEqual(account["deadline"], "2027-03-31")

    def test_issuer_credit_fixture_uses_credits_not_purchases_and_requires_coverage(self):
        resy = calculate_benefit(self.db, "fixture:resy-credit", as_of="2026-09-26")
        self.assertEqual(resy["used_amount_minor"], 2000)
        self.assertEqual(resy["supporting_transaction_ids"], ["fixture:resy-credit-posted"])
        uber = calculate_benefit(self.db, "fixture:uber-statement-credit", as_of="2026-10-15")
        self.assertEqual(uber["used_amount_minor"], 1500)
        self.assertEqual(uber["supporting_transaction_ids"], ["fixture:uber-credit-posted"])
        incomplete = calculate_benefit(self.db, "fixture:uber-statement-credit", as_of="2026-10-16")
        self.assertEqual(incomplete["status"], "unknown")
        self.assertIn("coverage is incomplete", incomplete["reason"])

    def test_issuer_credit_eval_cases_pass_deterministic_agent_plan(self):
        import json
        cases = json.loads((Path(__file__).parents[1] / "evals/cases.json").read_text())
        targets = {"resy-quarterly-issuer-credit", "uber-monthly-issuer-credit",
                   "uber-credit-incomplete-statement-coverage"}
        for case in (item for item in cases if item["id"] in targets):
            captured = []
            answer = answer_with_db(self.db, case["question"],
                                    client=PlannedAgentClient(tool_plan(case)),
                                    embedder=FixtureEmbedder(),
                                    on_tool_result=lambda tool, result: captured.append({"tool": tool, "result": result}))
            self.assertEqual(factual_checks(case["expected"], captured, answer), [], case["id"])

    def test_missing_amount_and_unknown_merchant_remain_unknown(self):
        missing = calculate_benefit(self.db, "fixture:incomplete-credit", as_of="2026-10-15")
        self.assertEqual(missing["status"], "unknown")
        unclear = calculate_benefit(self.db, "fixture:unclear-credit", as_of="2026-10-15")
        self.assertEqual(unclear["status"], "unknown")

    def test_fixture_contains_official_sources_and_dated_community_idea(self):
        self.assertIsNotNone(self.db.execute(
            "SELECT 1 FROM sources WHERE source_id = 'fixture:airline-fee-terms'").fetchone())
        idea = self.db.execute(
            "SELECT idea_id, source_url, source_date FROM community_ideas").fetchone()
        self.assertEqual(idea, ("fixture:idea-1", "https://example.test/community/1", "2026-09-01"))


if __name__ == "__main__":
    unittest.main()
