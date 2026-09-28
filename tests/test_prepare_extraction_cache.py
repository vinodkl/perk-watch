"""Extraction is billed and worded by a model, so re-running prepare on unchanged sources must
not re-call it: a persisted, content-hash-keyed cache should make a second run free and produce
byte-identical terms text, and embeddings for that unchanged text should be carried forward
rather than re-embedded. See docs/explanation/perk-watch-v3-benefit-tracker.md.

Uses an unstructured (prose, non-JSON) benefit guide so the extractor is called once per
document with the whole text -- the same "no prior terms to compare against" shape that let
the old DB-comparison cache silently miss on real data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.prepare.run import prepare


class RecordingExtractor:
    """Simulates a temperature-0 model that still rewords its output slightly on every real
    call, so a broken cache would drift the stored terms (and their embeddings) on every rerun."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, source):
        self.calls.append(source)
        call_number = len(self.calls)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [{"benefit_id": f"amex_platinum_benefit_{index:03d}", "title": line.split(":")[0],
                 "terms": f"{line} (worded call {call_number})", "amount_minor": 700,
                 "period": "monthly", "eligible_merchants": ["resy"]}
                for index, line in enumerate(lines, 1)]


class FakeEmbedder:
    model = "test-embedding"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[float(len(text))] for text in texts]


class PrepareExtractionCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "raw/amex-platinum/benefits").mkdir(parents=True)
        (self.root / "raw/amex-platinum/transactions").mkdir()
        (self.root / "raw/chase-sapphire-preferred/benefits").mkdir(parents=True)
        (self.root / "raw/chase-sapphire-preferred/transactions").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _write_guide(self, line_two="Digital entertainment credit: get $20 monthly for streaming."):
        text = f"Travel credit: get up to $200 per year for airline fees.\n{line_two}\n"
        path = self.root / "raw/amex-platinum/benefits/guide.txt"
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode()).hexdigest()
        index = self.root / "raw/amex-platinum/sources.json"
        index.write_text(json.dumps({"schema_version": 1, "card_id": "amex_platinum", "sources": [
            {"card_id": "amex_platinum", "kind": "benefits", "filename": "guide.txt",
             "path": "raw/amex-platinum/benefits/guide.txt", "content_sha256": digest},
        ]}), encoding="utf-8")

    def test_rerun_on_unchanged_sources_makes_zero_extraction_calls_and_identical_terms(self):
        self._write_guide()
        extractor = RecordingExtractor()

        first = prepare(self.root, extractor=extractor)
        second = prepare(self.root, extractor=extractor)

        self.assertEqual(first["cards"]["amex_platinum"]["extraction_calls"], 1)
        self.assertNotIn("extraction_calls", second["cards"]["amex_platinum"])
        self.assertEqual(second["cards"]["amex_platinum"]["extraction_reused"], 1)
        self.assertEqual(len(extractor.calls), 1, "the model must not be called again on the second run")

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            rows = dict(db.execute("SELECT title, terms FROM benefits WHERE card_id = 'amex_platinum'"))
        self.assertEqual(rows["Travel credit"], "Travel credit: get up to $200 per year for airline fees. (worded call 1)")
        self.assertIn("(worded call 1)", rows["Digital entertainment credit"])

        cache_path = self.root / "prepared/extraction_cache.json"
        self.assertTrue(cache_path.exists())
        cache = json.loads(cache_path.read_text())
        self.assertEqual(len(cache["entries"]), 1)

    def test_changed_source_triggers_exactly_one_re_extraction(self):
        self._write_guide()
        extractor = RecordingExtractor()
        prepare(self.root, extractor=extractor)

        self._write_guide(line_two="Digital entertainment credit: get $25 monthly for streaming, revised.")
        second = prepare(self.root, extractor=extractor)

        self.assertEqual(second["cards"]["amex_platinum"]["extraction_calls"], 1)
        self.assertNotIn("extraction_reused", second["cards"]["amex_platinum"])
        self.assertEqual(len(extractor.calls), 2, "only the changed source should trigger a fresh call")

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            rows = dict(db.execute("SELECT title, terms FROM benefits WHERE card_id = 'amex_platinum'"))
        self.assertIn("$25", rows["Digital entertainment credit"])
        self.assertIn("(worded call 2)", rows["Digital entertainment credit"])

    def test_rerun_with_unchanged_terms_reuses_embeddings_instead_of_rebuilding(self):
        self._write_guide()
        extractor = RecordingExtractor()
        embedder = FakeEmbedder()

        prepare(self.root, extractor=extractor, embedder=embedder)
        calls_after_first = embedder.calls
        self.assertGreater(calls_after_first, 0)

        second = prepare(self.root, extractor=extractor, embedder=embedder)

        self.assertEqual(embedder.calls, calls_after_first, "unchanged terms text must not be re-embedded")
        self.assertEqual(second["cards"]["amex_platinum"]["embeddings"], 2)

        with sqlite3.connect(self.root / "prepared/perkwatch.sqlite") as db:
            hashes = [row[0] for row in db.execute(
                "SELECT content_sha256 FROM benefit_embeddings ORDER BY benefit_id")]
        self.assertEqual(len(set(hashes)), 2)

    def test_changed_terms_re_embeds_only_the_changed_benefit(self):
        self._write_guide()
        extractor = RecordingExtractor()
        embedder = FakeEmbedder()
        prepare(self.root, extractor=extractor, embedder=embedder)

        self._write_guide(line_two="Digital entertainment credit: get $25 monthly for streaming, revised.")
        embedder.calls = 0
        prepare(self.root, extractor=extractor, embedder=embedder)

        # One embed() call batches every changed row in the card; only the streaming credit changed.
        self.assertEqual(embedder.calls, 1)


if __name__ == "__main__":
    unittest.main()
