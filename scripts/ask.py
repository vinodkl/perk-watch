#!/usr/bin/env python3
"""Ask a question about your tracked card credits."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.runtime.app import data_root, database
from perk_watch.runtime.chat import wallet_ask
from perk_watch.runtime.profile import load_marks

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("question", nargs="+", help="question about your card credits")
parser.add_argument("--data-root", type=Path, default=None)
parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
args = parser.parse_args()
try:
    db = database(args.data_root)
    try:
        reply = wallet_ask(db, [{"role": "user", "content": " ".join(args.question)}],
                           as_of=args.as_of, marks=load_marks(data_root(args.data_root)))
    finally:
        db.close()
except (FileNotFoundError, RuntimeError) as exc:
    parser.error(str(exc))
print(reply["answer"])
if reply["unverified_amounts"]:
    print(f"\n(unverified amounts: {', '.join(reply['unverified_amounts'])})")
