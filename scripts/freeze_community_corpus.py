#!/usr/bin/env python3
"""Freeze a locally stored public Reddit corpus without network access."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from perk_watch.community import freeze_snapshot

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
    if candidates["corpus_version"] != args.version:
        raise ValueError("corpus version does not match its directory")
    benefits = load(ROOT / "data/frozen/terms/benefits.json")["benefits"]
    manifest = freeze_snapshot(
        candidates["candidates"], load(corpus / "model_judgments.json")["judgments"],
        benefit_ids=(row["benefit_id"] for row in benefits), terms_version=candidates["terms_version"],
        output_dir=corpus / "snapshot", corpus_version=args.version,
        production_index_dir=args.data_root / "derived/indexes/community",
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
