#!/usr/bin/env python3
"""Small offline acceptance check for VKU-17."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefits import load_persisted_benefits
from perk_watch.rule_registry import SQLiteRuleRegistry


def main() -> None:
    clauses = [
        {"clause_id": "ok", "benefit_id": "amex_platinum_test", "terms_version": "t1",
         "source_id": "guide", "effective_from": "2026-01-01", "text": "up to $25 each month.",
         "period_type": "monthly", "period_amount_minor": 2500,
         "eligibility": {"merchant_group": "test"}},
        {"clause_id": "bad", "benefit_id": "amex_platinum_bad", "terms_version": "t1",
         "source_id": "guide", "text": "up to $25 each month.", "period_type": "quarterly",
         "period_amount_minor": 2500, "eligibility": {"merchant_group": "test"}},
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "registry.sqlite3"
        registry = SQLiteRuleRegistry(path=path)
        def extractor(clause):
            from perk_watch.rule_registry import extract_rule
            proposal = extract_rule(clause)
            if clause["clause_id"] == "bad":
                proposal["period_type"] = "monthly"
            return proposal

        result = registry.ingest(clauses, extractor=extractor)
        assert result == {"accepted": 1, "rejected": 1, "skipped": 0}
        assert [row.benefit_id for row in registry.active_benefits()] == ["amex_platinum_test"]
        assert {row["outcome"] for row in registry.decisions()} == {"supported", "disagreement"}
        restarted = SQLiteRuleRegistry(path=path)
        assert [row.benefit_id for row in restarted.active_benefits()] == ["amex_platinum_test"]
        assert load_persisted_benefits(path)[0].period_amount_minor == 2500
    print("rule_registry: accepted=1 rejected=1 restart=stable")


if __name__ == "__main__":
    main()
