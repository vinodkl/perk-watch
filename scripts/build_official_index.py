#!/usr/bin/env python3
"""Build the local official-clause index; this command may call OpenAI embeddings."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openai import OpenAI
from perk_watch.official_rag import DEFAULT_MODEL, OpenAIEmbeddingClient, build_official_index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    root = Path(os.environ.get("PERKWATCH_DATA_DIR", Path.home() / ".local/share/perk-watch"))
    index = build_official_index(root, OpenAIEmbeddingClient(OpenAI(api_key=api_key)), model=args.model)
    print(f"built {index.manifest['clause_count']} clauses using {index.manifest['embedding_model']}")
