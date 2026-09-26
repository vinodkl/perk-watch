#!/usr/bin/env python3
"""Show current prepared benefit calculations for both cards."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.runtime.app import database
from perk_watch.runtime.calculations import calculate_all


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-root", type=Path, default=None)
parser.add_argument("--as-of", help="Calculation date, YYYY-MM-DD")
parser.add_argument("--account-year-start", help="Account-year start, YYYY-MM-DD")
args = parser.parse_args()

db = database(args.data_root)
try:
    print(json.dumps(calculate_all(db, as_of=args.as_of,
                                   account_year_start=args.account_year_start), indent=2))
finally:
    db.close()
