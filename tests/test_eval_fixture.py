from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))
from fixture import STATEMENT_LINES, FixtureEmbedder, build_fixture
from perk_watch.catalog import load_catalog
from perk_watch.runtime.retrieval.search import search_benefits
from suites import run_tracker

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))


class EvalFixtureTest(unittest.TestCase):
    def setUp(self):
        self.db = build_fixture()

    def tearDown(self):
        self.db.close()

    def test_fixture_has_every_catalog_benefit_with_terms_and_embeddings(self):
        ids = {row[0] for row in self.db.execute("SELECT benefit_id FROM benefits WHERE terms <> ''")}
        self.assertEqual(ids, {b.benefit_id for b in load_catalog()})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM benefit_embeddings").fetchone()[0], len(ids))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], len(STATEMENT_LINES))

    def test_synthetic_tracker_cases_all_pass(self):
        report = run_tracker(self.db, CASES["tracker"])
        self.assertEqual(report["mismatches"], [])
        self.assertEqual((report["status_accuracy"], report["amount_accuracy"]), (1.0, 1.0))

    def test_tracker_cases_cover_every_status(self):
        statuses = {p["status"] for scenario in CASES["tracker"] for p in scenario["periods"]}
        self.assertEqual(statuses, {"used", "partial", "missed", "pending", "unmarked", "at_risk", "open"})

    def test_fixture_search_finds_clear_for_airport_security(self):
        top = search_benefits(self.db, "airport security fast lane", embedder=FixtureEmbedder(), limit=1)
        self.assertEqual(top[0]["benefit_id"], "amex_platinum_219_clear_credit")

    def test_run_tracker_reports_mismatches(self):
        scenario = {"name": "wrong", "as_of": "2026-09-26", "periods": [
            {"benefit_id": "amex_platinum_400_resy_credit", "period": "Q1", "status": "missed", "used_minor": 0}],
            "totals": {"captured_minor": 1}}
        report = run_tracker(self.db, [scenario])
        self.assertEqual(report["status_accuracy"], 0.0)
        self.assertEqual(len(report["mismatches"]), 2)


if __name__ == "__main__":
    unittest.main()
