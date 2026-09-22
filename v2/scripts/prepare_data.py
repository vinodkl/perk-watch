#!/usr/bin/env python3
"""Prepare local V2 data. Never prints rows or source content."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from perk_watch.prepare import prepare


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare PerkWatch V2 local card data")
    parser.add_argument("--data-dir", default=os.environ.get("PERKWATCH_DATA_DIR"), help="local data root")
    parser.add_argument("--model", default="gpt-4o-mini", help="structured extraction model, used only with OPENAI_API_KEY")
    args = parser.parse_args()
    if not args.data_dir:
        parser.error("set PERKWATCH_DATA_DIR or pass --data-dir")
    extractor = merchant_chooser = None
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        from perk_watch.prepare.extractor import OpenAIBenefitExtractor
        from perk_watch.prepare.merchants import OpenAIMerchantChooser
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        extractor = OpenAIBenefitExtractor(client, args.model)
        merchant_chooser = OpenAIMerchantChooser(client, args.model)
    report = prepare(args.data_dir, extractor=extractor, merchant_chooser=merchant_chooser)
    summary = {card: {key: value for key, value in stats.items() if key in {"benefits", "transactions", "credit_matches", "skipped", "community_skipped"}} for card, stats in report["cards"].items()}
    print(json.dumps({"cards": summary, "unresolved_count": report["unresolved_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
