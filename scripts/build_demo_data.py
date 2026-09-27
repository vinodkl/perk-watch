#!/usr/bin/env python3
"""Build a disposable demo data root through the real preparation pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.prepare import prepare
from perk_watch.staging.raw_data import import_benefit_guide, import_transactions


def main() -> None:
    parser = argparse.ArgumentParser(description="Build synthetic PerkWatch demo data")
    parser.add_argument("--root", required=True, type=Path, help="new data root outside the repository")
    args = parser.parse_args()
    target = args.root.expanduser().resolve()
    if target == ROOT or target.is_relative_to(ROOT):
        parser.error("--root must be outside the repository")
    if target.exists() and any(target.iterdir()):
        parser.error("--root must be empty")

    seed = ROOT / "demo" / "seed"
    for card in ("amex_platinum", "chase_sapphire_preferred", "chase_sapphire_reserve"):
        import_benefit_guide(seed / f"{card}-benefits.json", card=card, root=target,
                             url="https://example.test/perkwatch-demo")
        import_transactions(seed / f"{card}-transactions.csv", card=card, root=target)
        community = target / "raw" / card.replace("_", "-") / "community"
        community.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed / f"{card}-tips.json", community / "tips.json")
    # No blurb writer: the demo builds offline and deterministically, so blurbs stay empty.
    report = prepare(target)
    print(json.dumps({"root": str(target), "cards": report["cards"], "blurbs": report["blurbs"],
                      "unresolved_count": report["unresolved_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
