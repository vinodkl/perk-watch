#!/usr/bin/env python3
"""Build the optional local served-community index; this command may call OpenAI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openai import OpenAI
from perk_watch.community_rag import COMMUNITY_INDEX_RELATIVE_PATH, CommunityIdeaIndex
from perk_watch.official_rag import DEFAULT_MODEL, OpenAIEmbeddingClient


def corpus_paths(root: Path) -> list[Path]:
    paths = []
    for pointer in sorted((root / "prepared/community").glob("*/current.json")):
        current = json.loads(pointer.read_text(encoding="utf-8"))
        paths.append(root / current["path"] / "served_ideas.json")
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT_MODEL))
    parser.add_argument("--index-dir", type=Path)
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    root = Path(os.environ.get("PERKWATCH_DATA_DIR", Path.home() / ".local/share/perk-watch"))
    target = args.index_dir or root / COMMUNITY_INDEX_RELATIVE_PATH
    index = CommunityIdeaIndex.build(corpus_paths(root), target, OpenAIEmbeddingClient(OpenAI(api_key=api_key)), model=args.model)
    print(f"built {index.manifest['idea_count']} served ideas using {index.manifest['embedding_model']}")
