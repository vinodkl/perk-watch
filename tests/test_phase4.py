from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.catalog import load_catalog
from perk_watch.prepare.blurbs import blurb_prompt, generate_blurbs
from perk_watch.prepare.storage import connect
from perk_watch.runtime.community import blurb_for, tips_for
from perk_watch.runtime.retrieval.search import CommunitySearch
from perk_watch.prepare.rag_search_index import build_community_embeddings, build_community_tip_embeddings
from perk_watch.embeddings import idea_hash


class FakeEmbedder:
    model = "test"
    words = ("travel", "hotel", "booking", "credit", "dining")

    def embed(self, texts):
        return [[float(text.lower().count(word)) for word in self.words] for text in texts]


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.db.executemany("INSERT INTO cards VALUES (?, ?)", [("amex", "Amex"), ("chase", "Chase")])
        self.db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", [
            ("a", "amex", "benefits", "a.json", "a"), ("c", "chase", "benefits", "c.json", "c")])
        self.db.executemany("INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, enrollment_required, booking_required, terms, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("hotel", "amex", "Hotel credit", 10000, "yearly", "", None, None, "Official terms", "a"),
            ("dining", "chase", "Dining credit", 5000, "monthly", "", None, None, "Official terms", "c")])
        self.db.executemany("INSERT INTO community_ideas VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ("idea1", "amex", "hotel", "Book through the travel portal", "Try portal booking", "https://reddit.com/1", "v1", "2026-01-02"),
            ("idea2", "chase", "dining", "Use for dining", "Dining idea", "https://reddit.com/2", "v2", "2026-01-03"),
            ("undated", "amex", "hotel", "Undated", "Undated", "https://reddit.com/3", "v1", "")])
        self.db.execute(
            "INSERT INTO community_tips VALUES ('tip1', 'amex', 'hotel', "
            "'Try booking a hotel package through the travel portal for extra points', "
            "'https://example.test/tip1', 'Forum', '2026-01-05', '2026-01-06')")
        self.embedder = FakeEmbedder()

    def tearDown(self):
        self.db.close()

    def test_search_filters_by_card_and_benefit_and_returns_dated_labeled_link(self):
        self.assertEqual(build_community_embeddings(self.db, self.embedder), 3)
        result = CommunitySearch(self.db, self.embedder).search("hotel booking", card_id="amex", benefit_id="hotel")
        self.assertEqual([item["idea_id"] for item in result], ["idea1"])
        self.assertEqual(result[0]["source_date"], "2026-01-02")
        self.assertEqual(result[0]["source_url"], "https://reddit.com/1")
        self.assertEqual(result[0]["label"], "Community suggestion")

    def test_build_community_tip_embeddings_persists_model_and_content_hash(self):
        """Tips are embedded offline (prepare time) the same way ideas are: never a runtime call."""
        self.assertEqual(build_community_tip_embeddings(self.db, self.embedder), 1)
        row = self.db.execute(
            "SELECT model, content_sha256 FROM community_tip_embeddings WHERE tip_id = 'tip1'").fetchone()
        self.assertEqual(row[0], "test")
        self.assertEqual(row[1], idea_hash(
            "Try booking a hotel package through the travel portal for extra points",
            "https://example.test/tip1"))

    def test_search_merges_dated_ideas_with_embedded_tips_and_labels_each(self):
        build_community_embeddings(self.db, self.embedder)
        build_community_tip_embeddings(self.db, self.embedder)
        result = CommunitySearch(self.db, self.embedder).search("hotel booking", card_id="amex", benefit_id="hotel")
        self.assertEqual({item["label"] for item in result}, {"Community suggestion", "Community tip"})
        tip_hit = next(item for item in result if item["label"] == "Community tip")
        self.assertEqual(tip_hit["source_url"], "https://example.test/tip1")
        self.assertEqual(tip_hit["benefit_id"], "hotel")

    def test_stale_tip_content_is_excluded_from_search_until_reembedded(self):
        """The content-hash staleness check applies to tips exactly as it does to official terms and ideas."""
        build_community_tip_embeddings(self.db, self.embedder)
        self.db.execute("UPDATE community_tips SET tip = 'Completely different wording now' WHERE tip_id = 'tip1'")
        result = CommunitySearch(self.db, self.embedder).search("hotel booking", card_id="amex", benefit_id="hotel")
        self.assertFalse(any(item["label"] == "Community tip" for item in result))

def _add_tip(self, benefit_id, tip, tip_id):
        self.db.execute("INSERT INTO community_tips VALUES (?, 'amex', ?, ?, 'https://example.test/t', 'Thread', '2026-09-01', '2026-09-20')",
                        (tip_id, benefit_id, tip))


class FakeWriter:
    model = "fake-model"

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return f"People  do thing {len(self.prompts)}.\n"


class BlurbTests(unittest.TestCase):
    RESY = "amex_platinum_400_resy_credit"
    DE = "amex_platinum_300_digital_entertainment_credit"

    def setUp(self):
        self.db = connect(":memory:")
        self.db.execute("INSERT INTO cards VALUES ('amex', 'Amex')")
        self.catalog = tuple(b for b in load_catalog() if b.benefit_id in {self.RESY, self.DE})
        _add_tip(self, self.RESY, "Book on Resy early.", "t1")
        self.db.execute("INSERT INTO community_ideas VALUES ('i1', 'amex', ?, 'Pay the whole bill on the card.', 'x', 'https://reddit.com/1', 'v1', '')",
                        (self.RESY,))

    def tearDown(self):
        self.db.close()

    def test_blurb_summarizes_only_that_benefits_tips_with_the_prototype_prompt(self):
        writer = FakeWriter()
        stats = generate_blurbs(self.db, writer, self.catalog)
        self.assertEqual(stats, {"written": 1, "cached": 0, "removed": 0, "pending": 0})
        self.assertEqual(writer.prompts, [blurb_prompt(["Book on Resy early.", "Pay the whole bill on the card."])])
        self.assertTrue(writer.prompts[0].startswith("In at most 2 short sentences"))
        self.assertIn("Start with 'People'. No links.", writer.prompts[0])
        self.assertEqual(blurb_for(self.db, self.RESY), "People do thing 1.")
        self.assertEqual(blurb_for(self.db, self.DE), "")
        self.assertEqual(self.db.execute("SELECT model FROM community_blurbs").fetchone()[0], "fake-model")
        self.assertEqual([t["tip"] for t in tips_for(self.db, self.RESY)],
                         ["Book on Resy early.", "Pay the whole bill on the card."])

    def test_unchanged_tips_reuse_the_cached_blurb_and_changed_tips_regenerate(self):
        writer = FakeWriter()
        generate_blurbs(self.db, writer, self.catalog)
        self.assertEqual(generate_blurbs(self.db, writer, self.catalog)["cached"], 1)
        self.assertEqual(len(writer.prompts), 1)
        _add_tip(self, self.RESY, "Split across two visits.", "t2")
        self.assertEqual(generate_blurbs(self.db, writer, self.catalog)["written"], 1)
        self.assertEqual(blurb_for(self.db, self.RESY), "People do thing 2.")

    def test_without_a_writer_blurbs_are_skipped_and_stale_ones_removed(self):
        generate_blurbs(self.db, FakeWriter(), self.catalog)
        self.assertEqual(generate_blurbs(self.db, None, self.catalog)["cached"], 1)
        _add_tip(self, self.RESY, "New tip.", "t3")
        stats = generate_blurbs(self.db, None, self.catalog)
        self.assertEqual((stats["pending"], stats["removed"]), (1, 1))
        self.assertIn("no writer", stats["note"])
        self.assertEqual(blurb_for(self.db, self.RESY), "")

    def test_blurb_is_removed_when_its_benefit_has_no_tips_left(self):
        generate_blurbs(self.db, FakeWriter(), self.catalog)
        self.db.execute("DELETE FROM community_tips")
        self.db.execute("DELETE FROM community_ideas")
        self.assertEqual(generate_blurbs(self.db, FakeWriter(), self.catalog)["removed"], 1)
        self.assertEqual(blurb_for(self.db, self.RESY), "")

if __name__ == "__main__":
    unittest.main()
