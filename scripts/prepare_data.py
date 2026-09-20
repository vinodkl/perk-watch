#!/usr/bin/env python3
"""Normalize every card's raw benefits, transactions, and community notes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.preparation import prepare_data


if __name__ == "__main__":
    print(json.dumps(prepare_data(), indent=2, sort_keys=True))
