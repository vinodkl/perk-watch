#!/usr/bin/env python3
"""Generate a DRAFT benefit-classification scaffold and a review worksheet.

Both outputs are local-only (under PERKWATCH_DATA_DIR/derived/registry/) and are
never active. Applying a mapping requires a separate, explicitly reviewed file
at ``benefit-classification.json`` (``reviewed: true``).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefit_mapping import DRAFT_FILENAME, build_draft_mapping, registry_dir
from perk_watch.raw_data import data_root


def main() -> None:
    root = data_root()
    corpus_path = root / "prepared" / "benefits" / "current.json"
    if not corpus_path.exists():
        raise SystemExit("no prepared benefit corpus; run scripts/prepare_data.py first")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    clauses = corpus.get("clauses", [])
    terms_version = str(corpus.get("terms_version") or "")
    draft = build_draft_mapping(
        clauses, terms_version, generated_at=datetime.now(timezone.utc).isoformat()
    )

    directory = registry_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    draft_path = directory / DRAFT_FILENAME
    draft_path.write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    worksheet_path = directory / "worksheet.md"
    worksheet_path.write_text(_worksheet(draft), encoding="utf-8")

    print(f"draft_mapping: {draft_path}")
    print(f"worksheet: {worksheet_path}")
    print(f"slug_rows: {draft['tallies']['total_real_benefits']}")
    print("reviewed_mapping: absent (apply requires reviewed:true at benefit-classification.json)")


def _worksheet(draft: dict) -> str:
    lines = [
        "# PerkWatch benefit-mapping review worksheet (DRAFT)",
        "",
        "Status: **DRAFT — not reviewed, never active.**",
        f"Terms version: `{draft.get('terms_version')}`",
        f"Generated: {draft.get('generated_at')}",
        "",
        "Review each row and set one disposition:",
        "- `supported` — needs `merchant_group`, `period_type`, and (when dollar-capped) `period_amount_minor`.",
        "- `indeterminate` — leave for a later decision.",
        "- `known_untrackable` — needs `missing_data_source`.",
        "",
        "Then mark the mapping `reviewed: true` and save it as",
        "`derived/registry/benefit-classification.json`, then run `scripts/prepare_data.py`.",
        "",
        "| # | card | clause_slug | clauses | disposition | merchant_group | period_type | amount_minor | enrollment | portal | effective_from | effective_to | missing_data_source |",
        "|---|------|-------------|---------|-------------|----------------|-------------|--------------|------------|--------|----------------|--------------|---------------------|", 
    ]
    for index, row in enumerate(draft["benefits"], 1):
        lines.append(
            f"| {index} | {row['card']} | {row['clause_slug']} | "
            f"{len(row['governing_clause_ids'])} | {row['disposition']} |  |  |  |  |  |  |  |"
        )
    chase = [row for row in draft["benefits"] if row["card"] == "chase_sapphire_preferred"]
    if chase:
        lines.append("")
        lines.append("> Note: the chase guide was captured as unstructured text; re-capture it")
        lines.append("> as structured JSON to enumerate its per-benefit slugs before reviewing.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
