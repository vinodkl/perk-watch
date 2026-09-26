from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.staging.raw_data import import_benefit_guide, import_transactions
from perk_watch.cards import load_cards
from perk_watch.prepare.benefits import CARDS
from perk_watch.prepare.credits import match_credits
from perk_watch.prepare.run import _sources
from perk_watch.runtime.app import database


class StagingTests(unittest.TestCase):
    def test_catalog_drives_preparation_staging_and_credit_signs(self):
        cards = load_cards()
        self.assertEqual(set(cards), {"amex_platinum", "chase_sapphire_preferred"})
        self.assertEqual(CARDS, {card: info["display_name"] for card, info in cards.items()})
        benefit = [{"benefit_id": "credit", "title": "Hotel credit"}]
        for card, sign in (("amex_platinum", -100), ("chase_sapphire_preferred", 100)):
            rows = [{"transaction_id": "yes", "description": "Hotel credit", "amount_minor": sign},
                    {"transaction_id": "no", "description": "Hotel credit", "amount_minor": -sign}]
            self.assertEqual([row["transaction_id"] for row in match_credits(card, rows, benefit)], ["yes"])
        with tempfile.TemporaryDirectory() as temp:
            guide = Path(temp) / "guide.json"
            guide.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_benefit_guide(guide, card="chase_sapphire_reserve", root=Path(temp) / "data")

    def test_runtime_database_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "prepared").mkdir()
            sqlite3.connect(root / "prepared/perkwatch.sqlite").close()
            db = database(root)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("CREATE TABLE unwanted (id INTEGER)")
            finally:
                db.close()

    def test_import_is_idempotent_and_preparation_reads_registered_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            guide = Path(temp) / "guide.json"
            guide.write_text('{"benefits": []}', encoding="utf-8")
            first = import_benefit_guide(guide, card="amex_platinum", root=root)
            self.assertEqual(first, import_benefit_guide(guide, card="amex_platinum", root=root))
            index = root / "raw/amex-platinum/sources.json"
            self.assertEqual(len(json.loads(index.read_text())["sources"]), 1)
            self.assertEqual(_sources(index)[0]["source_id"], first["source_id"])
            self.assertEqual((root / first["path"]).read_bytes(), guide.read_bytes())
            export = Path(temp) / "transactions.csv"
            export.write_text("date,amount\n", encoding="utf-8")
            second = import_transactions(export, card="amex_platinum", root=root)
            self.assertEqual(second["kind"], "transactions")
            self.assertEqual(len(json.loads(index.read_text())["sources"]), 2)
            with self.assertRaises(ValueError):
                import_transactions(guide, card="amex_platinum", root=root)


if __name__ == "__main__":
    unittest.main()
