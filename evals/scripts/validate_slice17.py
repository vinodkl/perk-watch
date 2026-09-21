#!/usr/bin/env python3
"""Small offline acceptance check for VKU-17."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefit_mapping import load_benefit_mapping
from perk_watch.benefits import load_persisted_benefits
from perk_watch.raw_data import data_root
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

    # When the reviewed real mapping exists, the real registry must reflect it.
    mapping = load_benefit_mapping(data_root(), require_reviewed=True)
    real_note = "absent"
    if mapping.reviewed:
        real_registry = SQLiteRuleRegistry(path=data_root() / "prepared" / "rules" / "registry.sqlite3")
        active = real_registry.active_benefits()
        active_benefit_ids = {benefit.benefit_id for benefit in active}
        expected = sum(row.get("disposition") == "supported" for row in mapping.rows)
        assert len(active_benefit_ids) == expected, (
            f"expected {expected} active benefits, got {len(active_benefit_ids)} "
            f"across {len(active)} active rules"
        )
        real_note = f"verified ({len(active_benefit_ids)} active benefits from {len(active)} active rules)"
    print(f"real_registry: {real_note}")


if __name__ == "__main__":
    main()
