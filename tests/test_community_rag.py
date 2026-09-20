from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

from perk_watch.community_rag import CommunityIdeaIndex, baseline, rerank, retrieval_metrics


@dataclass
class Item:
    index: int
    embedding: list[float]


@dataclass
class Response:
    data: list[Item]


class FakeEmbedder:
    def create(self, *, model, input):
        vectors = {"hotel idea": [1.0, 0.0], "airline idea": [0.0, 1.0], "hotel query": [1.0, 0.0]}
        return Response([Item(i, vectors[text]) for i, text in enumerate(input)])


class CommunityRagTest(unittest.TestCase):
    def test_only_served_current_terms_are_indexed_and_labeled(self):
        rows = {
            "ideas": [
                {"idea_id": "served", "benefit_id": "hotel", "idea": "hotel idea", "excerpt": "paraphrase",
                 "source_date": "2026-01-01", "source_url": "https://www.reddit.com/x", "corpus_version": "c1",
                 "terms_version": "t1", "review_label": "no_known_conflict", "served": True},
                {"idea_id": "conflict", "benefit_id": "hotel", "idea": "hotel idea", "excerpt": "bad",
                 "source_date": "2026-01-01", "source_url": "https://www.reddit.com/y", "corpus_version": "c1",
                 "terms_version": "t1", "review_label": "explicit_conflict", "served": False},
                {"idea_id": "old", "benefit_id": "hotel", "idea": "hotel idea", "excerpt": "old",
                 "source_date": "2026-01-01", "source_url": "https://www.reddit.com/z", "corpus_version": "c1",
                 "terms_version": "old", "review_label": "no_known_conflict", "served": True},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "served.json"
            corpus.write_text(json.dumps(rows))
            index = CommunityIdeaIndex.build([corpus], root / "index", FakeEmbedder(), model="test")
            result = index.search("hotel query", benefit_id="hotel", terms_version="t1", embedder=FakeEmbedder())
            self.assertEqual([row["idea_id"] for row in result], ["served"])
            self.assertEqual(result[0]["labels"], ["non-authoritative", "unverified"])
            self.assertEqual(baseline(rows["ideas"], benefit_id="hotel", terms_version="t1")[0]["idea_id"], "served")

    def test_rerank_preserves_metadata_and_ids(self):
        rows = [{"idea_id": "a", "idea": "a"}, {"idea_id": "b", "idea": "b"}]
        result = rerank("query", rows, lambda _query, _rows: ["b", "a"])
        self.assertEqual([row["idea_id"] for row in result], ["b", "a"])
        self.assertEqual(result[0]["idea"], "b")

    def test_metrics_keep_exact_counts(self):
        metrics = retrieval_metrics([
            {"retrieved": ["a", "b"], "relevant": ["b"], "rows": [{"quote_verbatim": False, "stale": False}]},
            {"retrieved": ["c"], "relevant": ["d"], "rows": [{"quote_verbatim": True, "stale": True}]},
        ])
        self.assertEqual(metrics["recall_at_5"], {"numerator": 1, "denominator": 2, "value": 0.5})
        self.assertEqual(metrics["mrr"], {"numerator": 0.5, "denominator": 2, "value": 0.25})
        self.assertEqual(metrics["quote_verbatim_rate"]["numerator"], 1)
        self.assertEqual(metrics["staleness_flag_rate"]["denominator"], 2)


if __name__ == "__main__":
    unittest.main()
