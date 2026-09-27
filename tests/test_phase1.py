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
from perk_watch.prepare.community import load_ideas, load_tips, tip_id
from perk_watch.prepare.extractor import OpenAIBenefitExtractor
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
             "source_id": "post-1", "source_paraphrase": "Short paraphrase", "source_url": "https://reddit.com/keep", "terms_version": "current"},
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
        (latest / "collection_results.json").write_text(json.dumps({"benefits": [{"sources": [
            {"id": "post-1", "source_date": "2026-01-02"}]}]}))

        ideas, stats = load_ideas("amex_platinum", community, {"amex_platinum_travel"}, "current")

        self.assertEqual([row["idea_id"] for row in ideas], ["keep"])
        self.assertEqual(ideas[0]["excerpt"], "Short paraphrase")
        self.assertEqual(ideas[0]["source_date"], "2026-01-02")
        self.assertEqual(stats, {"processed": 1, "skipped": 2})

    def test_merchant_and_credit_matching_modules_are_gone(self):
        import importlib
        for name in ("perk_watch.prepare.merchants", "perk_watch.prepare.credits"):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(name)

    def test_prepare_keeps_merchant_null_and_writes_no_match_tables(self):
        benefit = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_300_lululemon_credit", "title": "$300 lululemon Credit", "terms": "terms"
        }]})
        transactions = (
            "Date,Description,Amount\n"
            "09/20/2026,Platinum Lululemon Credit,-75.00\n"
            "09/21/2026,WHOLE FOODS MARKET,12.34\n"
        )
        self._source("amex-platinum", "benefits", "guide.json", benefit)
        self._source("amex-platinum", "transactions", "transactions.csv", transactions)

        prepare(self.root)

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            merchants = [row[0] for row in db.execute("select merchant from transactions")]
            tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
        self.assertEqual(merchants, [None, None])
        self.assertFalse({"merchant_matches", "credit_matches"} & tables)

    def test_prepare_tolerates_an_older_database_with_match_tables(self):
        prepared = self.root / "prepared"
        prepared.mkdir()
        with sqlite3.connect(prepared / "perkwatch.sqlite") as db:
            db.executescript("""
                CREATE TABLE cards (card_id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
                CREATE TABLE sources (source_id TEXT PRIMARY KEY, card_id TEXT NOT NULL, kind TEXT NOT NULL,
                  path TEXT NOT NULL, content_sha256 TEXT NOT NULL);
                CREATE TABLE transactions (transaction_id TEXT PRIMARY KEY, card_id TEXT NOT NULL,
                  posted_date TEXT NOT NULL, description TEXT NOT NULL, amount_minor INTEGER NOT NULL,
                  currency TEXT NOT NULL, merchant TEXT, source_id TEXT NOT NULL);
                CREATE TABLE merchant_matches (transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id),
                  merchant TEXT, confidence TEXT NOT NULL);
                INSERT INTO cards VALUES ('amex_platinum', 'Amex Platinum');
                INSERT INTO sources VALUES ('s', 'amex_platinum', 'transactions', 'x.csv', 'x');
                INSERT INTO transactions VALUES ('t', 'amex_platinum', '2026-01-01', 'OLD', 1, 'USD', 'uber', 's');
                INSERT INTO merchant_matches VALUES ('t', 'uber', 'exact');
                CREATE TABLE credit_matches (transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id),
                  benefit_id TEXT NOT NULL, confidence TEXT NOT NULL);
                INSERT INTO credit_matches VALUES ('t', 'amex_platinum_x', 'explicit');
            """)
        self._source("amex-platinum", "transactions", "t.csv", "Date,Description,Amount\n09/20/2026,COFFEE,4.00\n")

        report = prepare(self.root)

        self.assertEqual(report["cards"]["amex_platinum"]["transactions"], 1)

    def test_tips_keep_only_catalog_benefits_with_https_sources(self):
        path = self.root / "raw/amex-platinum/community/tips.json"
        path.parent.mkdir(parents=True)
        good = {"benefit_id": "amex_platinum_400_resy_credit", "tip": "Book  early in the quarter.",
                "source_url": "https://example.test/1", "source_title": "Thread", "source_date": "2026-09-01",
                "last_verified": "2026-09-20"}
        path.write_text(json.dumps({"collected_on": "2026-09-26", "no_longer_works": [], "tips": [
            good, dict(good),
            {**good, "benefit_id": "amex_platinum_not_in_catalog"},
            {**good, "tip": "Plain http source", "source_url": "http://example.test/2"},
            {**good, "benefit_id": "chase_sapphire_preferred_benefit_001", "tip": "Other card"},
        ]}), encoding="utf-8")

        tips, stats = load_tips(path, {"amex_platinum_400_resy_credit"})

        self.assertEqual(stats, {"processed": 1, "skipped": 4})
        self.assertEqual(tips[0]["tip"], "Book early in the quarter.")
        self.assertEqual(tips[0]["tip_id"], tip_id("amex_platinum_400_resy_credit", "Book early in the quarter."))
        self.assertEqual(len(tips[0]["tip_id"]), 16)
        self.assertEqual((tips[0]["source_title"], tips[0]["last_verified"]), ("Thread", "2026-09-20"))

    def test_prepare_stores_tips_and_reports_catalog_gaps_and_unmatched_credit_lines(self):
        benefit = json.dumps({"benefits": [{
            "benefit_id": "amex_platinum_400_resy_credit", "title": "$400 Resy Credit", "terms": "Resy terms"
        }]})
        transactions = (
            "Date,Description,Amount\n"
            "03/20/2026,Platinum Resy Credit,-100.00\n"
            "03/21/2026,Mystery Statement Credit,-10.00\n"
            "03/22/2026,Store credit purchase,10.00\n"
        )
        self._source("amex-platinum", "benefits", "guide.json", benefit)
        self._source("amex-platinum", "transactions", "t.csv", transactions)
        self._source("chase-sapphire-preferred", "transactions", "t.csv",
                     "Date,Description,Amount\n03/20/2026,Unknown Chase Credit,5.00\n03/21/2026,Refund credit,-5.00\n")
        tips = self.root / "raw/amex-platinum/community/tips.json"
        tips.parent.mkdir(parents=True)
        tips.write_text(json.dumps({"tips": [
            {"benefit_id": "amex_platinum_400_resy_credit", "tip": "Book on Resy.", "source_url": "https://example.test/r"},
            {"benefit_id": "amex_platinum_unknown", "tip": "Dropped.", "source_url": "https://example.test/x"},
        ]}), encoding="utf-8")

        report = prepare(self.root)

        amex = report["cards"]["amex_platinum"]
        self.assertEqual((amex["tips_processed"], amex["tips_skipped"]), (1, 1))
        self.assertEqual(amex["unmatched_credit_lines"], 1)
        self.assertEqual(report["cards"]["chase_sapphire_preferred"]["unmatched_credit_lines"], 1)
        self.assertNotIn("amex_platinum_400_resy_credit", amex["catalog_missing_terms"])
        self.assertIn("amex_platinum_300_digital_entertainment_credit", amex["catalog_missing_terms"])
        self.assertIn({"kind": "catalog_terms", "benefit_id": "amex_platinum_300_digital_entertainment_credit"},
                      report["unresolved"])
        saved = json.loads((self.root / "prepared/report.json").read_text())
        self.assertEqual(saved["cards"]["amex_platinum"]["catalog_missing_terms"], amex["catalog_missing_terms"])
        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            rows = db.execute("select card_id, benefit_id, tip from community_tips").fetchall()
        self.assertEqual(rows, [("amex_platinum", "amex_platinum_400_resy_credit", "Book on Resy.")])

    def test_rerun_reuses_extracted_fields_when_terms_are_unchanged(self):
        document = json.dumps({"benefits": [
            {"benefit_id": "amex_platinum_one", "title": "One", "terms": "One terms"},
            {"benefit_id": "amex_platinum_two", "title": "Two", "terms": "Two terms"},
        ]})
        self._source("amex-platinum", "benefits", "guide.json", document)
        calls = []

        def extractor(text, _):
            item = json.loads(text)["benefits"][0]
            calls.append(item["benefit_id"])
            return [{**item, "amount_minor": 700, "period": "monthly", "eligible_merchants": ["resy", "uber"],
                     "enrollment_required": True}]

        first = prepare(self.root, extractor=extractor)
        second = prepare(self.root, extractor=extractor)

        self.assertEqual(calls, ["amex_platinum_one", "amex_platinum_two"])
        self.assertEqual(first["cards"]["amex_platinum"]["extraction_calls"], 2)
        self.assertEqual(second["cards"]["amex_platinum"]["extraction_reused"], 2)
        self.assertNotIn("extraction_calls", second["cards"]["amex_platinum"])
        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            row = db.execute("select amount_minor, period, eligible_merchants, enrollment_required from benefits "
                             "where benefit_id = 'amex_platinum_one'").fetchone()
        self.assertEqual(row, (700, "monthly", "resy,uber", 1))

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
            self.assertIsNone(db.execute("select merchant from transactions limit 1").fetchone()[0])
        self.assertEqual(report["cards"]["amex_platinum"]["transactions"], 1)
        self.assertTrue((self.root / "prepared/report.json").exists())


if __name__ == "__main__":
    unittest.main()
