from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

from perk_watch.official_rag import OfficialClauseIndex


@dataclass
class Item:
    index: int
    embedding: list[float]


@dataclass
class Response:
    data: list[Item]


class FakeEmbedder:
    def create(self, *, model, input):
        vectors = {
            "hotel": [1.0, 0.0],
            "airline": [0.0, 1.0],
        }
        return Response([Item(index, vectors[text]) for index, text in enumerate(input)])


class OfficialRagSmokeTest(unittest.TestCase):
    def test_build_search_and_metadata_filters(self):
        corpus = {
            "terms_version": "v2",
            "sources": {"amex:guide": {"card_id": "amex"}},
            "clauses": [
                {"clause_id": "hotel-old", "source_id": "amex:guide", "benefit_id": "hotel",
                 "terms_version": "v1", "effective_from": "2025-01-01", "effective_to": "2025-12-31", "text": "hotel"},
                {"clause_id": "hotel-new", "source_id": "amex:guide", "benefit_id": "hotel",
                 "terms_version": "v2", "effective_from": "2026-01-01", "effective_to": None, "text": "hotel"},
                {"clause_id": "airline", "source_id": "amex:guide", "benefit_id": "airline",
                 "terms_version": "v2", "effective_from": "2026-01-01", "effective_to": None, "text": "airline"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus_path = root / "current.json"
            corpus_path.write_text(json.dumps(corpus))
            index = OfficialClauseIndex.build(corpus_path, root / "index", FakeEmbedder(), model="test-model")
            results = index.search(
                "hotel", card_id="amex", benefit_id="hotel", as_of="2026-06-01",
                terms_version="v2", top_k=5, embedder=FakeEmbedder(),
            )
            self.assertEqual([row["clause_id"] for row in results], ["hotel-new"])
            self.assertEqual(results[0]["source_id"], "amex:guide")
            self.assertEqual(results[0]["citation"], "amex:guide")
            self.assertEqual(index.search("hotel", terms_version="missing", embedder=FakeEmbedder()), [])


if __name__ == "__main__":
    unittest.main()
