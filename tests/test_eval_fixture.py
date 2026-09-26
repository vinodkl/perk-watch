from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fixture import open_fixture
from perk_watch.calculations import calculate_benefit


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
