from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi.testclient import TestClient

from evals.fixture import open_fixture
from perk_watch.api.app import create_app
from perk_watch.runtime.app import database
from perk_watch.runtime.briefing import build_briefing


class Phase8Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        prepared = self.root / "prepared"
        prepared.mkdir()
        open_fixture(prepared / "perkwatch.sqlite").close()
        (prepared / "report.json").write_text(json.dumps({
            "finished_at": "2026-09-26T12:00:00+00:00",
            "cards": {"fixture:amex": {"benefits": 7}, "fixture:chase": {"benefits": 1}},
            "unresolved_count": 2,
        }), encoding="utf-8")
        self.client = TestClient(create_app(self.root))

    def tearDown(self):
        self.temporary.cleanup()

    def test_briefing_groups_calculations_and_statement_freshness(self):
        with closing(database(self.root)) as db:
            result = build_briefing(db, as_of="2026-09-26", window_days=14)
        self.assertIn("fixture:quarterly-credit", {
            row["benefit_id"] for row in result["groups"]["act_soon"]})
        self.assertIn("fixture:account-year-credit", {
            row["benefit_id"] for row in result["groups"]["check_yourself"]})
        self.assertIn("fixture:travel-credit", {
            row["benefit_id"] for row in result["groups"]["on_track"]})
        self.assertEqual(sum(row["count"] for row in result["unknown_reason_groups"]),
                         len(result["groups"]["check_yourself"]))

        with closing(database(self.root)) as db:
            stale = build_briefing(db, as_of="2026-11-01")["statements"]
        self.assertTrue(all(card["stale"] for card in stale))

    def test_read_routes_return_status_benefit_and_supporting_transactions(self):
        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["last_preparation_time"], "2026-09-26T12:00:00+00:00")
        self.assertEqual(len(status.json()["cards"]), 2)

        briefing = self.client.get("/api/briefing", params={"as_of": "2026-09-26"})
        self.assertEqual(briefing.status_code, 200)
        self.assertEqual(briefing.json()["as_of"], "2026-09-26")

        benefit = self.client.get("/api/benefits/fixture:travel-credit",
                                  params={"as_of": "2026-09-26"})
        self.assertEqual(benefit.status_code, 200)
        self.assertEqual(benefit.json()["calculation"]["used_amount_minor"], 2000)
        self.assertEqual(benefit.json()["source_reference"]["source_id"],
                         "fixture:travel-credit-terms")

        transactions = self.client.get(
            "/api/benefits/fixture:travel-credit/transactions",
            params={"as_of": "2026-09-26"})
        self.assertEqual([row["transaction_id"] for row in transactions.json()["transactions"]],
                         ["fixture:travel-purchase"])
        self.assertEqual(self.client.get("/api/benefits/missing").status_code, 404)

    def test_runtime_connection_is_read_only(self):
        with closing(database(self.root)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO cards VALUES ('write', 'Write')")

    def test_demo_builder_uses_real_preparation_pipeline(self):
        demo_root = self.root / "demo-output"
        result = subprocess.run(
            [sys.executable, "scripts/build_demo_data.py", "--root", str(demo_root)],
            cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["unresolved_count"], 0)
        with closing(database(demo_root)) as db:
            briefing = build_briefing(db, as_of="2026-09-26")
        self.assertEqual(len(briefing["groups"]["act_soon"]), 1)
        self.assertEqual(len(briefing["groups"]["check_yourself"]), 1)
        self.assertTrue(briefing["groups"]["act_soon"][0]["partially_used"])

        refused = subprocess.run(
            [sys.executable, "scripts/build_demo_data.py", "--root", "demo/output"],
            cwd=Path(__file__).parents[1], text=True, capture_output=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("outside the repository", refused.stderr)


if __name__ == "__main__":
    unittest.main()
