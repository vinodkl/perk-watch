#!/usr/bin/env python3
"""Offline Slice 1.5 checks for a local public-community corpus."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from perk_watch.community import freeze_snapshot, stale_idea_ids

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("PERKWATCH_DATA_DIR"))
    args = parser.parse_args()
    if args.data_root is None:
        parser.error("set PERKWATCH_DATA_DIR or pass --data-root")
    corpus = args.data_root / "community" / args.version
    candidates = load(corpus / "candidates.json")
    judgments = load(corpus / "model_judgments.json")["judgments"]
    collection = load(corpus / "collection_results.json")
    benefits = load(ROOT / "data/frozen/terms/benefits.json")["benefits"]
    version, terms_version = candidates["corpus_version"], candidates["terms_version"]
    assert version == args.version
    served, conflicts, manifest = (load(corpus / "snapshot" / name) for name in (
        "served_ideas.json", "conflicting_ideas.json", "manifest.json"))
    expected = {row["benefit_id"] for row in benefits}
    results = collection["collection_results"]
    assert {row["benefit_id"] for row in results} == expected
    assert all(row["result_status"] in {"results_found", "no_usable_ideas"} for row in results)
    assert all((row["result_status"] == "no_usable_ideas" and not row["sources"]) or 10 <= len(row["sources"]) <= 20 for row in results)
    rows = served["ideas"] + conflicts["ideas"]
    required = {"idea_id", "benefit_id", "source_kind", "source_id", "source_url", "source_date", "fetched_at", "excerpt", "idea", "terms_version", "corpus_version"}
    assert all(required <= row.keys() for row in rows)
    assert all(row["source_kind"] == "post" and row["source_origin"] == "public_reddit" and row["source_url"].startswith("https://www.reddit.com/") for row in rows)
    assert all(row["terms_version"] == terms_version and row["corpus_version"] == version for row in rows)
    assert not stale_idea_ids(rows, terms_version)
    assert all(row["served"] and row["review_label"] == "no_known_conflict" for row in served["ideas"])
    assert all(not row["served"] and row["review_label"] == "explicit_conflict" for row in conflicts["ideas"])
    assert all(sum(row["benefit_id"] == benefit for row in served["ideas"]) <= 8 for benefit in expected)
    seeded = load(ROOT / "data/frozen/community/conflicting_ideas.json")["ideas"]
    correct = sum(row["review_label"].startswith("conflicts_") == row["expected_conflict"] for row in seeded)
    assert seeded and correct == len(seeded)
    assert manifest["model_review_only"] and not manifest["network_accessed"] and not manifest["production_index_modified"]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / version
        freeze_snapshot(candidates["candidates"], judgments, benefit_ids=expected, terms_version=terms_version,
                        output_dir=output, corpus_version=version,
                        production_index_dir=args.data_root / "derived/indexes/community")
        for name in ("served_ideas.json", "conflicting_ideas.json", "manifest.json"):
            assert (output / name).read_bytes() == (corpus / "snapshot" / name).read_bytes()
    try:
        freeze_snapshot(candidates["candidates"], judgments, benefit_ids=expected, terms_version=terms_version,
                        output_dir=args.data_root / "derived/indexes/community", corpus_version=version,
                        production_index_dir=args.data_root / "derived/indexes/community")
    except ValueError:
        pass
    else:
        raise AssertionError("snapshot builder accepted the production-index directory")
    print(f"corpus_version: {version}")
    print(f"public_sources: {sum(len(row['sources']) for row in results)}")
    print(f"served_ideas: {len(served['ideas'])}")
    print(f"conflicting_ideas: {len(conflicts['ideas'])}")
    print(f"seeded_conflict_detection_accuracy: {correct}/{len(seeded)}")
    print("observed_failures: []")


if __name__ == "__main__":
    main()
