#!/usr/bin/env python3
"""Print the credit tracker as a compact table."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.runtime.app import data_root, database
from perk_watch.runtime.profile import load_marks
from perk_watch.runtime.tracker import track

GLYPH = {"used": "●", "partial": "◐", "missed": "✗", "pending": "…", "unmarked": "?", "at_risk": "!", "open": "○"}


def money(minor: int) -> str:
    return f"${minor / 100:,.2f}"


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-root", type=Path, default=None)
parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD")
args = parser.parse_args()

db = database(args.data_root)
try:
    result = track(db, args.as_of, load_marks(data_root(args.data_root)))
finally:
    db.close()

print(f"as of {result['as_of']}  data through {result['data_through']}")
totals = result["totals"]
print(f"captured {money(totals['captured_minor'])} | missed {money(totals['missed_minor'])} | "
      f"at risk now {money(totals['at_risk_minor'])} | unmatched credit lines {result['unmatched_credit_lines']}")
for benefit in result["benefits"]:
    current = benefit["current"]
    dots = " ".join(f"{p['label']}{GLYPH.get(p['status'], '?')}" for p in benefit["periods"])
    print(f"{benefit['title'][:36]:36} {money(current['used_minor']):>8} / {money(current['amount_minor']):<8} "
          f"{current['status']:8} {current['days_left']:>3}d  {dots}")
