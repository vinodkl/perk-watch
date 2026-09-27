from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient

from perk_watch.api.app import create_app
from perk_watch.prepare.storage import connect
from perk_watch.runtime.app import database
from test_tracker import AMEX, CHASE, DE, RESY, UBER_CASH, FakeClient, _message

AS_OF = "2026-09-26"


def build_root(root: Path) -> None:
    rows = [(AMEX, "2026-08-11", "Platinum Digital Entertainment Credit", -2500),
            (AMEX, "2026-09-19", "COFFEE SHOP", 700),
            (CHASE, "2026-09-18", "COFFEE SHOP", 500)]
    with closing(connect(root / "prepared" / "perkwatch.sqlite")) as db:
        db.executemany("INSERT INTO cards VALUES (?, ?)", [(AMEX, "Amex Platinum"), (CHASE, "Chase Sapphire Preferred")])
        db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)",
                       [(f"s-{c}", c, "transactions", f"{c}.csv", "x") for c in (AMEX, CHASE)])
        db.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, 'USD', NULL, ?)",
                       [(f"t{i}", card, posted, desc, amount, f"s-{card}")
                        for i, (card, posted, desc, amount) in enumerate(rows)])
        db.execute("INSERT INTO community_tips (tip_id, card_id, benefit_id, tip, source_url, source_title, source_date) "
                   "VALUES ('tip1', ?, ?, 'Book a weekday dinner', 'https://example.com/t', 'Thread', '2026-07-01')", (AMEX, RESY))
        db.execute("INSERT INTO community_blurbs VALUES (?, 'People book weekday dinners.', 'test', 'x')", (RESY,))
        db.commit()
    (root / "prepared" / "report.json").write_text(json.dumps({"finished_at": "2026-09-20T12:00:00+00:00"}))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        build_root(self.root)
        self.client = TestClient(create_app(self.root))

    def tearDown(self):
        self.temporary.cleanup()

    def benefit(self, body: dict, benefit_id: str) -> dict:
        return next(b for b in body["benefits"] if b["benefit_id"] == benefit_id)

    def test_tracker_uses_as_of_and_reports_totals(self):
        body = self.client.get("/api/tracker", params={"as_of": AS_OF}).json()
        self.assertEqual(body["as_of"], AS_OF)
        self.assertEqual(body["data_through"][AMEX], "2026-09-19")
        self.assertEqual(set(body["totals"]), {"captured_minor", "missed_minor", "at_risk_minor"})
        de_aug = next(p for p in self.benefit(body, DE)["periods"] if p["label"] == "Aug")
        self.assertEqual((de_aug["status"], de_aug["used_minor"]), ("used", 2500))
        self.assertEqual(self.benefit(body, RESY)["current"]["status"], "at_risk")
        earlier = self.client.get("/api/tracker", params={"as_of": "2026-03-15"}).json()
        self.assertEqual(earlier["as_of"], "2026-03-15")
        self.assertEqual(self.client.get("/api/tracker", params={"as_of": "not-a-date"}).status_code, 422)

    def test_mark_toggles_manual_credit_and_persists_to_profile(self):
        url = f"/api/benefits/{UBER_CASH}/mark"
        state = self.client.post(url, json={"period_start": "2026-08-01", "as_of": AS_OF}).json()
        august = next(p for p in state["periods"] if p["start"] == "2026-08-01")
        self.assertTrue(august["marked"])
        self.assertEqual(august["status"], "used")
        profile = json.loads((self.root / "user" / "profile.json").read_text())
        self.assertEqual(profile["marks"], [{"benefit_id": UBER_CASH, "period_start": "2026-08-01",
                                             "amount_minor": august["amount_minor"]}])
        tracker = self.client.get("/api/tracker", params={"as_of": AS_OF}).json()
        self.assertTrue(next(p for p in self.benefit(tracker, UBER_CASH)["periods"] if p["start"] == "2026-08-01")["marked"])

        state = self.client.post(url, json={"period_start": "2026-08-01", "as_of": AS_OF}).json()
        self.assertFalse(next(p for p in state["periods"] if p["start"] == "2026-08-01")["marked"])
        self.assertEqual(json.loads((self.root / "user" / "profile.json").read_text())["marks"], [])

    def test_mark_uses_custom_amount_and_rejects_bad_requests(self):
        url = f"/api/benefits/{UBER_CASH}/mark"
        state = self.client.post(url, json={"period_start": "2026-07-01", "as_of": AS_OF, "amount_minor": 500}).json()
        self.assertEqual(next(p for p in state["periods"] if p["start"] == "2026-07-01")["used_minor"], 500)
        self.assertEqual(self.client.post(url, json={"period_start": "2026-07-15", "as_of": AS_OF}).status_code, 400)
        auto = self.client.post(f"/api/benefits/{DE}/mark", json={"period_start": "2026-09-01", "as_of": AS_OF})
        self.assertEqual(auto.status_code, 400)
        self.assertEqual(self.client.post("/api/benefits/nope/mark", json={"period_start": "2026-09-01"}).status_code, 404)
        self.assertEqual(json.loads((self.root / "user" / "profile.json").read_text())["marks"],
                         [{"benefit_id": UBER_CASH, "period_start": "2026-07-01", "amount_minor": 500}])

    def test_community_returns_blurb_and_tips_without_llm(self):
        body = self.client.get(f"/api/benefits/{RESY}/community").json()
        self.assertEqual(body["blurb"], "People book weekday dinners.")
        self.assertEqual([t["tip"] for t in body["tips"]], ["Book a weekday dinner"])
        self.assertEqual(set(body["tips"][0]), {"tip", "source_url", "source_title", "source_date", "last_verified"})
        self.assertEqual(self.client.get(f"/api/benefits/{DE}/community").json(), {"blurb": "", "tips": []})
        self.assertEqual(self.client.get("/api/benefits/nope/community").status_code, 404)

    def test_chat_and_ask_use_injected_client(self):
        fake = FakeClient([_message("You have $100 left on Resy."), _message("Use Resy first.")])
        client = TestClient(create_app(self.root, chat_client=fake))
        messages = [{"role": "user", "content": "What should I do?"}]
        reply = client.post(f"/api/benefits/{RESY}/chat", json={"messages": messages, "as_of": AS_OF}).json()
        self.assertEqual(reply, {"answer": "You have $100 left on Resy.", "tool_trace": [], "unverified_amounts": []})
        self.assertIn("BENEFIT CONTEXT", fake.requests[0]["messages"][1]["content"])
        reply = client.post("/api/ask", json={"messages": messages, "as_of": AS_OF}).json()
        self.assertEqual(reply["answer"], "Use Resy first.")
        self.assertIn("WALLET CONTEXT", fake.requests[1]["messages"][1]["content"])
        self.assertEqual(client.post("/api/benefits/nope/chat", json={"messages": messages}).status_code, 404)
        self.assertEqual(client.post("/api/ask", json={"messages": [{"role": "user"}]}).status_code, 422)

    def test_chat_without_openai_key_is_503(self):
        messages = [{"role": "user", "content": "hi"}]
        with patch("perk_watch.embeddings._api_key", return_value=None):
            chat = self.client.post(f"/api/benefits/{RESY}/chat", json={"messages": messages})
            ask = self.client.post("/api/ask", json={"messages": messages})
        self.assertEqual((chat.status_code, ask.status_code), (503, 503))
        self.assertIn("OPENAI_API_KEY", chat.json()["detail"])

    def test_status_reports_preparation_time_and_data_through(self):
        self.assertEqual(self.client.get("/api/status").json(), {
            "last_preparation_time": "2026-09-20T12:00:00+00:00",
            "data_through": {AMEX: "2026-09-19", CHASE: "2026-09-18"}})

    def test_runtime_connection_is_read_only(self):
        with closing(database(self.root)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO cards VALUES ('write', 'Write')")


if __name__ == "__main__":
    unittest.main()
