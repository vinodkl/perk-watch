from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.prepare.storage import connect
from perk_watch.embeddings import OpenAIEmbeddingProvider
from perk_watch.privacy import redact_pii
from perk_watch.runtime.retrieval.search import BenefitSearch
from perk_watch.prepare.rag_search_index import build_benefit_embeddings


class FakeEmbedder:
    model = "test-embedding"
    _aliases = {"rides": "travel", "ride": "travel", "transportation": "travel",
                "reimbursement": "credit", "reimburse": "credit", "refund": "credit",
                "annual": "yearly", "annually": "yearly"}
    _vocabulary = ("travel", "credit", "monthly", "quarterly", "yearly", "dining")

    def embed(self, texts):
        vectors = []
        for text in texts:
            words = [self._aliases.get(word.strip(".,?!"), word.strip(".,?!"))
                     for word in text.lower().split()]
            vectors.append([float(words.count(word)) for word in self._vocabulary])
        return vectors


class Phase2Test(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.db.executemany("INSERT INTO cards VALUES (?, ?)", [("amex", "Amex"), ("chase", "Chase")])
        self.db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", [
            ("old", "amex", "benefits", "benefits-2025-12-01.json", "old"),
            ("new", "amex", "benefits", "benefits-2026-01-01.json", "new"),
        ])
        self.embedder = FakeEmbedder()

    def tearDown(self):
        self.db.close()

    def _benefit(self, benefit_id="amex_monthly", amount=10000, period="monthly", merchants="uber"):
        self.db.execute("INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, enrollment_required, booking_required, terms, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (benefit_id, "amex", "Monthly travel", amount, period, merchants, None, None, "Travel terms", "new"))
        self.db.execute("UPDATE benefits SET mechanism = 'legacy' WHERE benefit_id = ?", (benefit_id,))
        self.db.commit()

    def test_openai_embedding_provider_batches_and_restores_order(self):
        calls = []

        class Embeddings:
            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(data=[
                    SimpleNamespace(index=1, embedding=[2.0]),
                    SimpleNamespace(index=0, embedding=[1.0]),
                ])

        provider = OpenAIEmbeddingProvider(SimpleNamespace(embeddings=Embeddings()), batch_size=2)
        self.assertEqual(provider.embed(["one", "two"]), [[1.0], [2.0]])
        self.assertEqual(calls[0]["model"], "text-embedding-3-small")

    def test_outbound_redaction_preserves_benefit_facts(self):
        text = "Jane Doe email jane@example.com card 4242 4242 4242 4242 gets $100 monthly on 2026-01-01"
        safe = redact_pii(text)
        self.assertNotIn("jane@example.com", safe)
        self.assertNotIn("4242 4242 4242 4242", safe)
        self.assertIn("$100 monthly", safe)
        self.assertIn("2026-01-01", safe)

    def test_prepare_persists_embeddings_and_search_reuses_them(self):
        self._benefit()
        self.assertEqual(build_benefit_embeddings(self.db, self.embedder), 1)
        stored = self.db.execute("SELECT model, dimensions FROM benefit_embeddings").fetchone()
        self.assertEqual(stored, ("test-embedding", 6))
        self.assertEqual(BenefitSearch(self.db, self.embedder).search("travel credit")[0]["benefit_id"], "amex_monthly")

    def test_search_skips_missing_or_stale_vectors_without_reembedding_text(self):
        self._benefit()
        calls = []
        embed = self.embedder.embed
        def recording(texts):
            calls.extend(texts)
            return embed(texts)
        self.embedder.embed = recording
        self.assertEqual(BenefitSearch(self.db, self.embedder).search("travel credit"), [])
        build_benefit_embeddings(self.db, self.embedder)
        calls.clear()
        self.assertEqual(BenefitSearch(self.db, self.embedder).search("travel credit")[0]["benefit_id"], "amex_monthly")
        self.assertEqual(calls, ["travel credit"])
        self.db.execute("UPDATE benefits SET terms = ? WHERE benefit_id = ?", ("Changed travel terms", "amex_monthly"))
        calls.clear()
        self.assertEqual(BenefitSearch(self.db, self.embedder).search("travel credit"), [])
        self.assertEqual(calls, ["travel credit"])

    def test_search_returns_source_and_respects_card_and_date_filters(self):
        self.db.execute("INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, enrollment_required, booking_required, terms, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("old_benefit", "amex", "Travel credit", 100, "monthly", "uber", None, None, "Old travel terms", "old"))
        self.db.execute("INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, enrollment_required, booking_required, terms, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("new_benefit", "amex", "Travel credit", 100, "monthly", "uber", None, None, "New travel terms", "new"))
        self.db.commit()
        build_benefit_embeddings(self.db, self.embedder)
        results = BenefitSearch(self.db, self.embedder).search("travel credit", card_id="amex", as_of="2025-12-31")
        self.assertEqual([result["benefit_id"] for result in results], ["old_benefit"])
        self.assertEqual(results[0]["source_reference"]["source_id"], "old")

    def test_search_matches_paraphrases_but_rejects_unrelated_questions(self):
        self._benefit("rides", period="monthly", merchants="uber")
        self.db.execute("UPDATE benefits SET title = ?, terms = ? WHERE benefit_id = ?",
                        ("Monthly rides credit", "Reimbursement for transportation each month", "rides"))
        self.db.commit()
        build_benefit_embeddings(self.db, self.embedder)
        results = BenefitSearch(self.db, self.embedder).search("travel credit for rides")
        self.assertEqual(results[0]["benefit_id"], "rides")
        self.assertEqual(BenefitSearch(self.db, self.embedder).search("dining at restaurants"), [])


if __name__ == "__main__":
    unittest.main()
