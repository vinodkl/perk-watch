from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.prepare.rag_search_index import build_benefit_embeddings
from perk_watch.prepare.storage import connect
from perk_watch.runtime.retrieval.search import cards_named, search_benefits


class FakeEmbedder:
    model = "test-embedding"
    _vocabulary = ("hotel", "travel", "dining", "credit")

    def embed(self, texts):
        return [[float(text.lower().count(word)) for word in self._vocabulary] for text in texts]


class CardFilterTest(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.db.executemany("INSERT INTO cards VALUES (?, ?)", [
            ("amex_platinum", "Amex Platinum"), ("chase_sapphire_preferred", "Chase Sapphire Preferred")])
        self.db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", [
            ("s-amex", "amex_platinum", "benefits", "amex.json", "x"),
            ("s-chase", "chase_sapphire_preferred", "benefits", "chase.json", "x")])
        self.db.executemany(
            "INSERT INTO benefits (benefit_id, card_id, title, terms, source_id) VALUES (?, ?, ?, ?, ?)", [
                # The Amex text says "hotel" more often, so it wins when no card is named.
                ("amex_hotel", "amex_platinum", "Hotel Credit", "hotel hotel hotel credit", "s-amex"),
                ("chase_hotel", "chase_sapphire_preferred", "Travel Hotel Credit", "hotel travel credit", "s-chase"),
                ("chase_dining", "chase_sapphire_preferred", "Dining Credit", "dining credit", "s-chase")])
        self.embedder = FakeEmbedder()
        build_benefit_embeddings(self.db, self.embedder)

    def tearDown(self):
        self.db.close()

    def top(self, question, **filters):
        return [hit["benefit_id"] for hit in search_benefits(self.db, question, embedder=self.embedder, **filters)]

    def test_cards_named_matches_display_name_words(self):
        self.assertEqual(cards_named(self.db, "Does my Sapphire card cover hotels?"), {"chase_sapphire_preferred"})
        self.assertEqual(cards_named(self.db, "amex hotel credit"), {"amex_platinum"})
        self.assertEqual(cards_named(self.db, "Which card has a preferred hotel credit?"), set())

    def test_naming_a_card_restricts_results_to_that_card(self):
        self.assertEqual(self.top("hotel credit")[0], "amex_hotel")
        self.assertEqual(self.top("Sapphire hotel credit"), ["chase_hotel", "chase_dining"])
        self.assertEqual(self.top("Chase or Amex hotel credit")[0], "amex_hotel")

    def test_explicit_card_filter_still_wins(self):
        self.assertEqual(self.top("Sapphire hotel credit", card_id="amex_platinum"), ["amex_hotel"])


if __name__ == "__main__":
    unittest.main()
