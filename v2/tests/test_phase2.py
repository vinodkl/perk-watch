from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.prepare.storage import connect
from perk_watch.calculations import calculate_benefit
from perk_watch.search import BenefitSearch


class Phase2Test(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.db.executemany("INSERT INTO cards VALUES (?, ?)", [("amex", "Amex"), ("chase", "Chase")])
        self.db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", [
            ("old", "amex", "benefits", "benefits-2025-12-01.json", "old"),
            ("new", "amex", "benefits", "benefits-2026-01-01.json", "new"),
        ])

    def tearDown(self):
        self.db.close()

    def _benefit(self, benefit_id="amex_monthly", amount=10000, period="monthly", merchants="uber"):
        self.db.execute("INSERT INTO benefits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (benefit_id, "amex", "Monthly travel", amount, period, merchants, None, None, "Travel terms", "new"))
        self.db.commit()

    def _transaction(self, transaction_id, posted, amount, merchant=None):
        self.db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (transaction_id, "amex", posted, merchant or "Unclear", amount, "USD", merchant, "new"))
        self.db.commit()

    def test_search_returns_source_and_respects_card_and_date_filters(self):
        self.db.execute("INSERT INTO benefits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("old_benefit", "amex", "Travel credit", 100, "monthly", "uber", None, None, "Old travel terms", "old"))
        self.db.execute("INSERT INTO benefits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("new_benefit", "amex", "Travel credit", 100, "monthly", "uber", None, None, "New travel terms", "new"))
        self.db.commit()
        results = BenefitSearch(self.db).search("travel credit", card_id="amex", as_of="2025-12-31")
        self.assertEqual([result["benefit_id"] for result in results], ["old_benefit"])
        self.assertEqual(results[0]["source_reference"]["source_id"], "old")

    def test_monthly_calculation_applies_refund_and_returns_transactions(self):
        self._benefit()
        self._transaction("purchase", "2026-01-05", 8000, "uber")
        self._transaction("refund", "2026-01-06", -2500, "uber")
        self._transaction("other", "2026-01-07", 9000, "whole foods")
        result = calculate_benefit(self.db, "amex_monthly", as_of="2026-01-15")
        self.assertEqual(result["used_amount_minor"], 5500)
        self.assertEqual(result["remaining_amount_minor"], 4500)
        self.assertEqual(result["deadline"], "2026-01-31")
        self.assertEqual(result["supporting_transaction_ids"], ["purchase", "refund"])

    def test_unknown_merchant_keeps_status_unknown(self):
        self._benefit()
        self._transaction("unknown", "2026-01-05", 1000)
        result = calculate_benefit(self.db, "amex_monthly", as_of="2026-01-15")
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["remaining_amount_minor"])

    def test_period_boundaries_and_missing_account_year_boundary(self):
        self._benefit("quarter", 1000, "quarterly")
        self._transaction("q", "2026-04-01", 1000, "uber")
        result = calculate_benefit(self.db, "quarter", as_of="2026-06-30")
        self.assertEqual(result["deadline"], "2026-06-30")

        self._benefit("account", 1000, "account-year")
        unknown = calculate_benefit(self.db, "account", as_of="2026-06-30")
        self.assertEqual(unknown["status"], "unknown")
        known = calculate_benefit(self.db, "account", as_of="2026-06-30", account_year_start="2025-07-01")
        self.assertEqual(known["deadline"], "2026-06-30")

    def test_missing_amount_is_unknown(self):
        self._benefit("missing", None)
        result = calculate_benefit(self.db, "missing", as_of="2026-01-15")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "benefit amount is unknown")


if __name__ == "__main__":
    unittest.main()
