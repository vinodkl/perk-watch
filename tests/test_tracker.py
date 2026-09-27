from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.catalog import load_catalog, match_credit
from perk_watch.prepare.storage import connect
from perk_watch.runtime.chat import benefit_chat, unverified_amounts
from perk_watch.runtime.profile import load_marks, toggle_mark
from perk_watch.runtime.tracker import track

AMEX, CHASE = "amex_platinum", "chase_sapphire_preferred"
DE = "amex_platinum_300_digital_entertainment_credit"
RESY = "amex_platinum_400_resy_credit"
UBER_CASH = "amex_platinum_200_uber_cash"
HOTEL = "amex_platinum_600_hotel_credit"
CHASE_HOTEL = "chase_sapphire_preferred_benefit_010"


def fixture_db(rows: list[tuple[str, str, str, int]]):
    """rows: (card_id, posted_date, description, amount_minor) in each card's export sign."""
    db = connect(":memory:")
    db.executemany("INSERT INTO cards VALUES (?, ?)", [(AMEX, "Amex Platinum"), (CHASE, "Chase Sapphire Preferred")])
    db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)",
                   [(f"s-{c}", c, "transactions", f"{c}.csv", "x") for c in (AMEX, CHASE)])
    db.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, 'USD', NULL, ?)",
                   [(f"t{i}", card, posted, desc, amount, f"s-{card}") for i, (card, posted, desc, amount) in enumerate(rows)])
    return db


def by_id(result: dict) -> dict[str, dict]:
    return {b["benefit_id"]: b for b in result["benefits"]}


class CatalogTest(unittest.TestCase):
    def test_catalog_loads_and_every_real_credit_line_matches_exactly_one_benefit(self):
        self.assertGreaterEqual(len(load_catalog()), 10)
        lines = {"Platinum Digital Entertainment Credit": DE, "PLATINUM RESY CREDIT": RESY,
                 "Platinum Lululemon Credit": "amex_platinum_300_lululemon_credit",
                 "Platinum Uber One Credit": "amex_platinum_120_uber_one_credit"}
        for line, expected in lines.items():
            self.assertEqual(match_credit(AMEX, line), expected)

    def test_unrelated_and_other_card_lines_do_not_match(self):
        self.assertIsNone(match_credit(AMEX, "UBER TRIP HELP.UBER.COM"))
        self.assertIsNone(match_credit(CHASE, "Platinum Resy Credit"))

    def test_manual_credits_have_no_pattern(self):
        manual = [b for b in load_catalog() if b.tracking == "manual"]
        self.assertTrue(manual)
        self.assertTrue(all(not b.credit_pattern for b in manual))


class TrackerTest(unittest.TestCase):
    def test_period_statuses_match_the_maxrewards_shape(self):
        db = fixture_db([
            (AMEX, "2026-01-11", "Platinum Digital Entertainment Credit", -2299),
            (AMEX, "2026-02-11", "Platinum Digital Entertainment Credit", -2500),
            (AMEX, "2026-03-28", "Platinum Resy Credit", -10000),
            (AMEX, "2026-04-20", "RESY RESTAURANT PURCHASE", 5000),
            (AMEX, "2026-04-22", "Platinum Digital Entertainment Credit", -2500),
            (AMEX, "2026-04-25", "COFFEE SHOP", 700),
        ])
        result = by_id(track(db, date(2026, 4, 25)))
        de = [(p["label"], p["status"], p["used_minor"]) for p in result[DE]["periods"]]
        self.assertEqual(de, [("Jan", "partial", 2299), ("Feb", "used", 2500), ("Mar", "missed", 0), ("Apr", "used", 2500)])
        self.assertEqual(result[DE]["ytd"], {"captured_minor": 7299, "missed_minor": 2701})
        resy = result[RESY]
        self.assertEqual([p["status"] for p in resy["periods"]], ["used", "open"])
        self.assertEqual(resy["current"]["days_left"], 67)
        self.assertEqual(resy["current"]["remaining_minor"], 10000)

    def test_at_risk_window_and_pending_after_statement_gap(self):
        db = fixture_db([(AMEX, "2026-03-25", "COFFEE SHOP", 700)])
        result = by_id(track(db, date(2026, 3, 26)))
        self.assertEqual(result[RESY]["current"]["status"], "at_risk")  # 6 days left <= 14
        self.assertEqual(result[HOTEL]["current"]["status"], "open")    # 97 days left > 30
        later = by_id(track(db, date(2026, 4, 2)))
        self.assertEqual(later[RESY]["periods"][0]["status"], "pending")  # statements stop Mar 25

    def test_manual_credits_are_unmarked_until_the_user_marks_them(self):
        db = fixture_db([(AMEX, "2026-03-31", "COFFEE SHOP", 700)])
        result = by_id(track(db, date(2026, 3, 15), marks={(UBER_CASH, "2026-02-01"): 1500}))
        self.assertEqual([p["status"] for p in result[UBER_CASH]["periods"]], ["unmarked", "used", "open"])

    def test_december_override_and_chase_positive_credit_sign(self):
        db = fixture_db([
            (CHASE, "2026-05-02", "CHASE TRAVEL HOTEL CREDIT", 10000),
            (CHASE, "2026-05-03", "HOTEL CREDIT REVERSAL", -10000),  # wrong sign for a Chase credit: ignored
        ])
        result = by_id(track(db, date(2026, 12, 5)))
        self.assertEqual(result[UBER_CASH]["current"]["amount_minor"], 3500)
        self.assertEqual(result[CHASE_HOTEL]["current"]["used_minor"], 10000)
        self.assertEqual(result[CHASE_HOTEL]["current"]["status"], "used")

    def test_totals_and_unmatched_credit_lines(self):
        db = fixture_db([(AMEX, "2026-01-05", "Platinum Mystery Credit", -1000),
                         (AMEX, "2026-01-06", "COFFEE SHOP", 700)])
        result = track(db, date(2026, 1, 28))
        self.assertEqual(result["unmatched_credit_lines"], 1)
        self.assertGreater(result["totals"]["at_risk_minor"], 0)
        self.assertEqual(result["data_through"][AMEX], "2026-01-06")


class ProfileTest(unittest.TestCase):
    def test_toggle_mark_persists_and_unmarks(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(load_marks(root), {})
            toggle_mark(root, UBER_CASH, "2026-08-01", 1500)
            self.assertEqual(load_marks(root), {(UBER_CASH, "2026-08-01"): 1500})
            self.assertTrue(json.loads((Path(root) / "user" / "profile.json").read_text())["marks"])
            toggle_mark(root, UBER_CASH, "2026-08-01", 1500)
            self.assertEqual(load_marks(root), {})


def _message(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


class ChatTest(unittest.TestCase):
    def test_benefit_chat_runs_tools_and_flags_invented_amounts(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_benefit_status", arguments=json.dumps({"benefit_id": RESY})))
        client = FakeClient([_message(tool_calls=[call]),
                             _message("You have $100 left for 5 days. A $250 dinner would also work.")])
        reply = benefit_chat(db, RESY, [{"role": "user", "content": "How do I use it?"}], as_of=date(2026, 9, 26), client=client)
        self.assertEqual([t["tool"] for t in reply["tool_trace"]], ["get_benefit_status"])
        self.assertEqual(reply["unverified_amounts"], ["$250"])
        context = client.requests[0]["messages"][1]["content"]
        self.assertIn('"remaining": 100.0', context)
        self.assertNotIn("COFFEE", context)  # transaction descriptions never reach the model

    def test_unverified_amounts_accepts_amounts_present_as_plain_numbers(self):
        self.assertEqual(unverified_amounts("Use $12.95 now", '{"remaining": 12.95}'), [])
        self.assertEqual(unverified_amounts("Use $1,000", '{"remaining": 12.95}'), ["$1,000"])


if __name__ == "__main__":
    unittest.main()
