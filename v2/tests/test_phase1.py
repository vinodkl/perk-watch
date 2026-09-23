from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.prepare.benefits import load_benefits
from perk_watch.prepare.community import load_ideas
from perk_watch.prepare.credits import match_credits
from perk_watch.prepare.extractor import OpenAIBenefitExtractor
from perk_watch.prepare.merchants import MERCHANTS, OpenAIMerchantChooser, match_all
from perk_watch.prepare.run import prepare
from perk_watch.prepare.transactions import load_transactions


class Phase1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for card in ("amex-platinum", "chase-sapphire-preferred"):
            (self.root / "raw" / card / "benefits").mkdir(parents=True)
            (self.root / "raw" / card / "transactions").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _source(self, card, kind, filename, content):
        card_dir = self.root / "raw" / card
        path = card_dir / kind / filename
        path.write_text(content, encoding="utf-8")
        import hashlib
        digest = hashlib.sha256(content.encode()).hexdigest()
        index = card_dir / "sources.json"
        document = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {"schema_version": 1, "card_id": card.replace("-", "_"), "sources": []}
        document["sources"].append({"card_id": card.replace("-", "_"), "kind": kind, "filename": filename, "path": path.relative_to(self.root).as_posix(), "content_sha256": digest})
        index.write_text(json.dumps(document), encoding="utf-8")

    def test_obvious_amount_and_period_are_repaired_locally(self):
        path = self.root / "raw/amex-platinum/benefits/guide.json"
        path.write_text(json.dumps({"benefits": [{
            "title": "Travel credit", "terms": "Receive a credit of $100 each month"
        }]}), encoding="utf-8")
        rows, _ = load_benefits("amex_platinum", path)
        self.assertEqual(rows[0]["amount_minor"], 10000)
        self.assertEqual(rows[0]["period"], "monthly")

    def test_invalid_llm_output_is_skipped_and_unknowns_are_saved(self):
        self._source("amex-platinum", "benefits", "guide.json", "{}")
        self._source("chase-sapphire-preferred", "benefits", "guide.json", "{}")
        values = [{"title": "Travel credit", "terms": "Current terms", "amount_minor": None}, {"bad": True}]
        rows, stats = load_benefits("amex_platinum", self.root / "raw/amex-platinum/benefits/guide.json", lambda *_: values)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_minor"], None)
        self.assertEqual(stats["skipped"], 1)

    def test_benefit_extractor_requests_local_structured_fields(self):
        class Completions:
            def create(self, **kwargs):
                system = kwargs["messages"][0]["content"]
                user = kwargs["messages"][1]["content"]
                self.request = (system, user)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps({"benefits": [{"title": "Travel", "terms": "Source terms", "amount_minor": 10000,
                                                       "period": "monthly", "eligible_merchants": ["uber"]}]})
                ))])

        completions = Completions()
        extractor = OpenAIBenefitExtractor(SimpleNamespace(chat=SimpleNamespace(completions=completions)))
        result = extractor("Local benefit text", "amex:benefits:source")

        self.assertEqual(result[0]["amount_minor"], 10000)
        self.assertIn("Do not browse", completions.request[0])
        self.assertIn("amex:benefits:source", completions.request[1])

    def test_incomplete_structured_benefits_are_extracted_one_at_a_time(self):
        document = json.dumps({"benefits": [
            {"benefit_id": "amex_platinum_one", "title": "One", "terms": "One terms"},
            {"benefit_id": "amex_platinum_two", "title": "Two", "terms": "Two terms"},
        ]})
        path = self.root / "raw/amex-platinum/benefits/guide.json"
        path.write_text(document, encoding="utf-8")
        calls = []

        def extractor(text, _):
            calls.append(json.loads(text)["benefits"][0]["title"])
            item = json.loads(text)["benefits"][0]
            return [{**item, "amount_minor": 100, "period": "monthly", "eligible_merchants": ["uber"]}]

        rows, _ = load_benefits("amex_platinum", path, extractor)
        self.assertEqual(calls, ["One", "Two"])
        self.assertEqual(len(rows), 2)

    def test_structured_benefit_json_bypasses_the_model_extractor(self):
        document = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_travel", "title": "Travel", "terms": "Exact issuer terms",
            "amount_minor": 10000, "period": "monthly", "eligible_merchants": ["uber"]
        }]})
        self._source("amex-platinum", "benefits", "guide.json", document)

        def unexpected_extractor(*_):
            raise AssertionError("structured JSON must not use the model")

        rows, _ = load_benefits(
            "amex_platinum", self.root / "raw/amex-platinum/benefits/guide.json", unexpected_extractor
        )

        self.assertEqual(rows[0]["terms"], "Exact issuer terms")

    def test_latest_versioned_community_candidates_are_joined_with_judgments(self):
        community = self.root / "raw/amex-platinum/community"
        old = community / "community-reddit-2026-09-21.v1"
        latest = community / "community-reddit-2026-09-21.v2"
        old.mkdir(parents=True)
        latest.mkdir()
        (old / "candidates.json").write_text(json.dumps({"candidates": [{
            "idea_id": "old", "benefit_id": "amex_platinum_travel", "idea": "Old idea",
            "source_url": "https://reddit.com/old", "terms_version": "current"
        }]}))
        (old / "model_judgments.json").write_text(json.dumps({"judgments": [{
            "idea_id": "old", "review_label": "no_known_conflict", "terms_version": "current"
        }]}))
        candidates = [
            {"idea_id": "keep", "benefit_id": "amex_platinum_travel", "idea": "Current idea",
             "source_paraphrase": "Short paraphrase", "source_url": "https://reddit.com/keep", "terms_version": "current"},
            {"idea_id": "conflict", "benefit_id": "amex_platinum_travel", "idea": "Conflicting idea",
             "source_url": "https://reddit.com/conflict", "terms_version": "current"},
            {"idea_id": "unreviewed", "benefit_id": "amex_platinum_travel", "idea": "Unreviewed idea",
             "source_url": "https://reddit.com/unreviewed", "terms_version": "current"},
        ]
        judgments = [
            {"idea_id": "keep", "review_label": "no_known_conflict", "terms_version": "current"},
            {"idea_id": "conflict", "review_label": "explicit_conflict", "terms_version": "current"},
        ]
        (latest / "candidates.json").write_text(json.dumps({"candidates": candidates}))
        (latest / "model_judgments.json").write_text(json.dumps({"judgments": judgments}))

        ideas, stats = load_ideas("amex_platinum", community, {"amex_platinum_travel"}, "current")

        self.assertEqual([row["idea_id"] for row in ideas], ["keep"])
        self.assertEqual(ideas[0]["excerpt"], "Short paraphrase")
        self.assertEqual(stats, {"processed": 1, "skipped": 2})

    def test_unknown_merchants_are_batched_through_a_fixed_list_chooser(self):
        calls = []

        def chooser(descriptions, merchants):
            calls.append((descriptions, merchants))
            return {"ubr trip": "uber", "mystery": "invented merchant"}

        matches = match_all(["UBER *TRIP 1234", "UBR TRIP 5678", "MYSTERY 9012"], chooser)

        self.assertEqual(calls, [(('ubr trip', 'mystery'), MERCHANTS)])
        self.assertEqual(matches, [("uber", "exact"), ("uber", "model"), (None, "unknown")])

    def test_openai_merchant_chooser_batches_json_requests(self):
        class Completions:
            def __init__(self):
                self.calls = 0

            def create(self, **kwargs):
                self.calls += 1
                request = json.loads(kwargs["messages"][-1]["content"])
                matches = [{"description": value, "merchant": "uber" if value.startswith("ubr") else None}
                           for value in request["descriptions"]]
                message = SimpleNamespace(content=json.dumps({"matches": matches}))
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        completions = Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        chooser = OpenAIMerchantChooser(client, batch_size=2)

        result = chooser(("ubr trip", "mystery", "other"), MERCHANTS)

        self.assertEqual(completions.calls, 2)
        self.assertEqual(result, {"ubr trip": "uber", "mystery": None, "other": None})

    def test_explicit_statement_credits_are_matched_without_replacing_merchant_matching(self):
        amex_benefits = [
            {"benefit_id": "amex_platinum_lululemon", "title": "$300 lululemon Credit"},
            {"benefit_id": "amex_platinum_hotel", "title": "$600 Hotel Credit"},
            {"benefit_id": "amex_platinum_hotel_collection", "title": "The Hotel Collection"},
        ]
        amex_transactions = [
            {"transaction_id": "credit", "description": "LULULEMON MEMBERSHIP CREDIT", "amount_minor": -7500},
            {"transaction_id": "purchase", "description": "LULULEMON", "amount_minor": 7500},
            {"transaction_id": "refund", "description": "LULULEMON REFUND", "amount_minor": -7500},
            {"transaction_id": "ambiguous", "description": "HOTEL CREDIT", "amount_minor": -10000},
        ]
        chase_benefits = [{
            "benefit_id": "chase_sapphire_preferred_hotel", "title": "$100 Annual Chase Travel Hotel Credit"
        }]
        chase_transactions = [{
            "transaction_id": "chase-credit", "description": "CHASE TRAVEL HOTEL CREDIT", "amount_minor": 10000
        }]

        self.assertEqual(match_credits("amex_platinum", amex_transactions, amex_benefits), [{
            "transaction_id": "credit", "benefit_id": "amex_platinum_lululemon", "confidence": "explicit"
        }])
        self.assertEqual(match_credits("chase_sapphire_preferred", chase_transactions, chase_benefits), [{
            "transaction_id": "chase-credit", "benefit_id": "chase_sapphire_preferred_hotel", "confidence": "explicit"
        }])

    def test_prepare_uses_the_batched_merchant_chooser(self):
        benefit = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_travel", "title": "Travel", "terms": "terms"
        }]})
        transactions = "Date,Description,Amount\n09/20/2026,UBR TRIP 1234,12.34\n"
        self._source("amex-platinum", "benefits", "guide.json", benefit)
        self._source("amex-platinum", "transactions", "transactions.csv", transactions)

        prepare(self.root, merchant_chooser=lambda descriptions, _: {descriptions[0]: "uber"})

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            match = db.execute("select merchant, confidence from merchant_matches").fetchone()
        self.assertEqual(match, ("uber", "model"))

    def test_prepare_stores_credit_and_merchant_matches_separately(self):
        benefit = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_lululemon", "title": "$300 lululemon Credit", "terms": "terms"
        }]})
        transactions = (
            "Date,Description,Amount\n"
            "09/20/2026,LULULEMON MEMBERSHIP CREDIT,-75.00\n"
            "09/21/2026,WHOLE FOODS MARKET,12.34\n"
        )
        self._source("amex-platinum", "benefits", "guide.json", benefit)
        self._source("amex-platinum", "transactions", "transactions.csv", transactions)

        prepare(self.root)

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            credit = db.execute("select benefit_id, confidence from credit_matches").fetchone()
            merchant = db.execute(
                "select merchant, confidence from merchant_matches where merchant = 'whole foods'"
            ).fetchone()
        self.assertEqual(credit, ("amex_platinum_lululemon", "explicit"))
        self.assertEqual(merchant, ("whole foods", "exact"))

    def test_provider_csv_headers_and_dates_are_normalized(self):
        amex = self.root / "amex.csv"
        chase = self.root / "chase.csv"
        amex.write_text(
            "Date,Description,Card Member,Account #,Amount\n09/20/2026,Example purchase,Person,00001,12.34\n"
        )
        chase.write_text(
            "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
            "09/20/2026,09/21/2026,Example purchase,Other,Sale,-45.67,\n"
        )

        amex_rows = load_transactions("amex_platinum", amex, "amex-source")
        chase_rows = load_transactions("chase_sapphire_preferred", chase, "chase-source")

        self.assertEqual((amex_rows[0]["posted_date"], amex_rows[0]["amount_minor"]), ("2026-09-20", 1234))
        self.assertEqual((chase_rows[0]["posted_date"], chase_rows[0]["amount_minor"]), ("2026-09-21", -4567))

    def test_repeated_preparation_replaces_stale_card_rows(self):
        old = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_old", "title": "Old", "terms": "old terms"
        }]})
        new = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_new", "title": "New", "terms": "new terms"
        }]})
        self._source("amex-platinum", "benefits", "guide.json", old)
        prepare(self.root)
        self._source("amex-platinum", "benefits", "guide.json", new)
        prepare(self.root)

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            ids = [row[0] for row in db.execute(
                "select benefit_id from benefits where card_id = 'amex_platinum' order by benefit_id"
            )]
        self.assertEqual(ids, ["amex_platinum_new"])

    def test_repeated_exports_are_deduplicated(self):
        benefit = json.dumps({"benefits": [{"benefit_id": "amex_platinum_travel", "title": "Travel", "terms": "terms"}]})
        csv_text = "date,description,amount,currency\n2025-01-02,WHOLE FOODS MARKET,12.34,USD\n"
        for card in ("amex-platinum", "chase-sapphire-preferred"):
            self._source(card, "benefits", "guide.json", benefit)
            self._source(card, "transactions", "one.csv", csv_text)
            self._source(card, "transactions", "two.csv", csv_text)
        report = prepare(self.root)
        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            self.assertEqual(db.execute("select count(*) from transactions").fetchone()[0], 2)
            self.assertEqual(db.execute("select amount_minor from transactions limit 1").fetchone()[0], 1234)
            self.assertEqual(db.execute("select merchant from merchant_matches limit 1").fetchone()[0], "whole foods")
        self.assertEqual(report["cards"]["amex_platinum"]["transactions"], 1)
        self.assertTrue((self.root / "prepared/report.json").exists())


if __name__ == "__main__":
    unittest.main()
