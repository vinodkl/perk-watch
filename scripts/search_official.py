#!/usr/bin/env python3
"""Search a previously built official-clause index."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openai import OpenAI
from perk_watch.official_rag import OfficialClauseIndex, OpenAIEmbeddingClient


parser = argparse.ArgumentParser()
parser.add_argument("query")
parser.add_argument("--card")
parser.add_argument("--benefit")
parser.add_argument("--as-of")
parser.add_argument("--terms-version")
parser.add_argument("--top-k", type=int, default=5)
args = parser.parse_args()
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("OPENAI_API_KEY is required")
root = Path(os.environ.get("PERKWATCH_DATA_DIR", Path.home() / ".local/share/perk-watch"))
index = OfficialClauseIndex(root / "prepared/indexes/official")
print(json.dumps(index.search(
    args.query, card_id=args.card, benefit_id=args.benefit, as_of=args.as_of,
    terms_version=args.terms_version, top_k=args.top_k,
    embedder=OpenAIEmbeddingClient(OpenAI(api_key=api_key)),
), indent=2, sort_keys=True))
