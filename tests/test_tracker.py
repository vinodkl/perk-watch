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
from perk_watch.prepare.rag_search_index import build_community_embeddings, build_community_tip_embeddings
from perk_watch.prepare.storage import connect
from perk_watch.runtime.chat import (TOOLS, _Session, benefit_chat, summarize_result, unverified_amounts,
                                     wallet_ask, wallet_briefing, BENEFIT_SYSTEM, BRIEFING_SYSTEM, MODEL,
                                     WALLET_SYSTEM)
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

    def test_summarize_result_covers_each_tool_and_errors(self):
        status = {"title": "$400 Resy Credit", "current_period": {"remaining": 45.0, "status": "at_risk"}}
        self.assertEqual(summarize_result("get_benefit_status", status), "$400 Resy Credit: $45.00 left, at_risk")
        self.assertEqual(summarize_result("search_terms", [{"title": "$219 CLEAR+ Credit"}, {"title": "$200 Airline Fee Credit"}]),
                         "found $219 CLEAR+ Credit, $200 Airline Fee Credit")
        self.assertEqual(summarize_result("search_terms", []), "no matching terms")
        self.assertEqual(summarize_result("get_community_tips", [{"tip": "a"}]), "1 community tip")
        self.assertEqual(summarize_result("get_community_tips", []), "0 community tips")
        self.assertEqual(summarize_result("get_benefit_status", {"error": "not a tracked benefit; tracked ids: [...]"}),
                         "error: not a tracked benefit; tracked ids: [...]")

    def test_reply_reports_step_summary_amounts_checked_and_model(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_benefit_status", arguments=json.dumps({"benefit_id": RESY})))
        client = FakeClient([_message(tool_calls=[call]), _message("You have $100 left, $100 by Sep 30.")])
        reply = benefit_chat(db, RESY, [{"role": "user", "content": "How do I use it?"}], as_of=date(2026, 9, 26), client=client)
        self.assertEqual(reply["tool_trace"], [{"tool": "get_benefit_status", "args": {"benefit_id": RESY},
                                                "summary": "$400 Resy Credit: $100.00 left, at_risk"}])
        self.assertEqual((reply["amounts_checked"], reply["model"]), (1, MODEL))

    def test_briefing_uses_wallet_context_tools_and_no_transaction_text(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_community_tips", arguments=json.dumps({"benefit_id": RESY})))
        client = FakeClient([_message(tool_calls=[call]), _message("- **$400 Resy Credit**: $100 left by Sep 30.")])
        reply = wallet_briefing(db, as_of=date(2026, 9, 26), client=client)
        first = client.requests[0]["messages"]
        self.assertEqual(first[0]["content"], BRIEFING_SYSTEM)
        self.assertTrue(first[1]["content"].startswith("WALLET CONTEXT:"))
        self.assertNotIn("COFFEE", first[1]["content"])
        self.assertEqual(first[2], {"role": "user", "content": "Write this week's plan."})
        self.assertEqual(reply["tool_trace"], [{"tool": "get_community_tips", "args": {"benefit_id": RESY},
                                                "summary": "0 community tips for $400 Resy Credit"}])
        self.assertEqual((reply["unverified_amounts"], reply["amounts_checked"]), ([], 2))

    def test_briefing_context_sorts_at_risk_credits_by_remaining_first(self):
        db = fixture_db([])
        client = FakeClient([_message("- plan")])
        wallet_briefing(db, as_of=date(2026, 9, 26), client=client)
        context = client.requests[0]["messages"][1]["content"]
        wallet = json.loads(context.split("WALLET CONTEXT:\n", 1)[1])
        self.assertEqual([item["title"] for item in wallet[:2]], ["$400 Resy Credit", "$300 lululemon Credit"])

    def test_tool_budget_caps_calls_within_a_single_round(self):
        db = fixture_db([])
        calls = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name="get_community_tips", arguments=json.dumps({"benefit_id": RESY})))
                 for i in range(6)]
        client = FakeClient([_message(tool_calls=calls), _message("Here you go.")])
        reply = wallet_briefing(db, as_of=date(2026, 9, 26), client=client)
        self.assertEqual(len(reply["tool_trace"]), 6)
        self.assertEqual(sum(1 for t in reply["tool_trace"] if t["summary"] != "skipped: tool budget spent"), 4)
        self.assertEqual(sum(1 for t in reply["tool_trace"] if t["summary"] == "skipped: tool budget spent"), 2)
        second = client.requests[1]["messages"]
        self.assertEqual(sum(1 for m in second if isinstance(m, dict) and m.get("role") == "tool"), 6)
        self.assertNotIn("tools", client.requests[1])

    def _propose(self, benefit_id, marks=None):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="propose_mark", arguments=json.dumps({"benefit_id": benefit_id})))
        client = FakeClient([_message(tool_calls=[call]), _message("Tap the button to confirm.")])
        return benefit_chat(fixture_db([]), benefit_id, [{"role": "user", "content": "I used it"}],
                            as_of=date(2026, 9, 26), marks=marks, client=client)

    def test_propose_mark_offers_the_current_manual_period(self):
        reply = self._propose(UBER_CASH)
        self.assertEqual(len(reply["proposals"]), 1)
        proposal = reply["proposals"][0]
        self.assertEqual((proposal["benefit_id"], proposal["period_start"], proposal["amount"]), (UBER_CASH, "2026-09-01", 15.0))
        self.assertTrue(reply["tool_trace"][0]["summary"].startswith("offered to mark $200 Uber Cash"))

    def test_propose_mark_refuses_auto_credits_and_marked_periods(self):
        self.assertEqual(self._propose(RESY)["proposals"], [])
        self.assertEqual(self._propose(UBER_CASH, marks={(UBER_CASH, "2026-09-01"): 1500})["proposals"], [])

    def test_wallet_ask_system_prompt_requires_tool_calls_for_history_questions(self):
        db = fixture_db([])
        client = FakeClient([_message("- **$300 lululemon Credit**: not used this quarter.")])
        wallet_ask(db, [{"role": "user", "content": "Have I used my lululemon credit reliably this year?"}],
                  as_of=date(2026, 9, 26), client=client)
        system = client.requests[0]["messages"][0]["content"]
        self.assertIn("call get_benefit_status for each credit involved", system)

    def test_benefit_and_wallet_system_prompts_require_the_literal_community_idea_label(self):
        for prompt in (BENEFIT_SYSTEM, WALLET_SYSTEM):
            self.assertIn("community_tips", prompt)
            self.assertIn('"Community idea"', prompt)
            self.assertIn("next to that link, every time", prompt)

    def test_reply_includes_usage_latency_and_cost(self):
        db = fixture_db([(AMEX, "2026-09-19", "COFFEE SHOP", 700)])
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_benefit_status", arguments=json.dumps({"benefit_id": RESY})))
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        message_with_tool = _message(tool_calls=[call])
        message_with_tool.usage = usage
        final = _message("You have $100 left, $100 by Sep 30.")
        final.usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10, total_tokens=60)
        client = FakeClient([message_with_tool, final])
        reply = benefit_chat(db, RESY, [{"role": "user", "content": "How do I use it?"}], as_of=date(2026, 9, 26), client=client)
        self.assertEqual(reply["usage"], {"model_calls": 2, "prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180})
        self.assertIsInstance(reply["latency_ms"], int)
        self.assertGreaterEqual(reply["latency_ms"], 0)
        self.assertEqual(reply["cost_usd"], round((150 * 0.15 + 30 * 0.60) / 1_000_000, 6))

    def test_reply_tolerates_missing_usage_on_the_fake_response(self):
        db = fixture_db([])
        client = FakeClient([_message("- plan")])
        reply = wallet_briefing(db, as_of=date(2026, 9, 26), client=client)
        self.assertEqual(reply["usage"], {"model_calls": 1, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        self.assertEqual(reply["cost_usd"], 0.0)


class CommunityTipSearchEmbedder:
    """Deterministic keyword vectors so the search tool needs no network."""
    model = "test-community-search"
    words = ("gym", "equinox", "billing", "resy", "restaurant")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.lower().count(word)) for word in self.words] for text in texts]


class SearchCommunityTipsToolTest(unittest.TestCase):
    """Community tips + ideas both come from prepared, embedded tables, never the network at runtime."""

    def setUp(self):
        self.db = connect(":memory:")
        self.db.execute("INSERT INTO cards VALUES (?, ?)", (AMEX, "Amex Platinum"))
        self.db.execute("INSERT INTO sources VALUES ('s1', ?, 'benefits', 'x.json', 'h')", (AMEX,))
        self.db.execute(
            "INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, "
            "enrollment_required, booking_required, terms, source_id) "
            "VALUES ('equinox', ?, '$300 Equinox Credit', 30000, 'annual', '', 1, 0, 'terms', 's1')", (AMEX,))
        self.db.execute(
            "INSERT INTO community_ideas VALUES ('idea1', ?, 'equinox', "
            "'Ask the gym front desk to apply the credit manually.', 'excerpt', "
            "'https://example.test/idea1', 'v1', '2026-01-01')", (AMEX,))
        self.db.execute(
            "INSERT INTO community_tips VALUES ('tip1', ?, 'equinox', "
            "'Call Equinox billing if the gym credit misses a month.', 'https://example.test/tip1', "
            "'Forum thread', '2026-02-01', '2026-02-10')", (AMEX,))
        self.embedder = CommunityTipSearchEmbedder()
        self.assertEqual(build_community_embeddings(self.db, self.embedder), 1)
        self.assertEqual(build_community_tip_embeddings(self.db, self.embedder), 1)

    def test_tool_is_registered_within_the_existing_call_budget(self):
        names = [t["function"]["name"] for t in TOOLS]
        self.assertIn("search_community_tips", names)
        self.assertEqual(len(names), 5)  # unchanged 4-call budget, one more tool to pick from

    def test_dispatch_returns_both_tables_labelled_as_community_not_official(self):
        session = _Session(self.db, date(2026, 9, 26), {}, client=FakeClient([]), embedder=self.embedder, model=MODEL)
        result = session.run_tool("search_community_tips", {"query": "gym equinox billing credit"})
        labels = {r["label"] for r in result}
        self.assertEqual(labels, {"Community suggestion", "Community tip"})
        for hit in result:
            self.assertEqual(hit["benefit_id"], "equinox")
            self.assertEqual(hit["benefit"], "$300 Equinox Credit")
            self.assertTrue(hit["tip"])  # normalized text field, whichever table it came from
            self.assertTrue(hit["source_url"].startswith("https://"))
            # never transaction descriptions or account data
            self.assertEqual(set(hit), {"benefit_id", "benefit", "card", "tip", "source_url", "source_date", "label"})

    def test_no_match_returns_empty_list(self):
        session = _Session(self.db, date(2026, 9, 26), {}, client=FakeClient([]), embedder=self.embedder, model=MODEL)
        self.assertEqual(session.run_tool("search_community_tips", {"query": "something unrelated entirely"}), [])

    def test_summarize_result_names_benefits_or_says_no_match(self):
        hits = [{"benefit": "$300 Equinox Credit"}, {"benefit": "$300 Equinox Credit"}]
        self.assertEqual(summarize_result("search_community_tips", hits),
                         "found 2 community tips: $300 Equinox Credit")
        self.assertEqual(summarize_result("search_community_tips", []), "no matching community tips")

    def test_wallet_ask_dispatches_the_tool_end_to_end(self):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(
            name="search_community_tips", arguments=json.dumps({"query": "gym equinox billing credit"})))
        client = FakeClient([_message(tool_calls=[call]),
                             _message("Community idea: call Equinox billing if a month is missed.")])
        reply = wallet_ask(self.db, [{"role": "user", "content": "How do people get their gym credit applied?"}],
                           as_of=date(2026, 9, 26), client=client, embedder=self.embedder)
        self.assertEqual(reply["tool_trace"][0]["tool"], "search_community_tips")
        self.assertTrue(reply["tool_trace"][0]["summary"].startswith("found 2 community tips: $300 Equinox Credit"))


if __name__ == "__main__":
    unittest.main()
