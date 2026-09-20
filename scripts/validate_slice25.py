#!/usr/bin/env python3
"""Offline Slice 2.5 scope-gate checks: data-driven matching and deferred surface."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefits import Benefit, load_benefit_registry, resolve_status
from perk_watch.transactions import ResolvedTransaction, Transaction


def main() -> None:
    benefits, merchant_groups, excluded = load_benefit_registry(
        ROOT / "data/frozen/terms/benefits.json",
        merchant_groups_path=ROOT / "data/frozen/terms/merchant_groups.json",
    )

    # Every trackable benefit routes matching through a named data-driven group.
    assert len(benefits) == 10
    assert all(benefit.merchant_group for benefit in benefits)
    assert all(benefit.merchant_group in merchant_groups for benefit in benefits)
    assert len(merchant_groups) == 14
    assert excluded == frozenset({"UBER CASH WALLET", "AIRLINE TICKET"})

    # Matching comes from data: the same charge is eligible with the group loaded
    # and not eligible when the group table is empty.
    lululemon = Benefit("amex_test_lululemon", "amex_platinum", "monthly", 5000, merchant_group="lululemon")
    charge = ResolvedTransaction(
        Transaction("t1", "amex_platinum", date(2026, 5, 1), date(2026, 5, 2), "LULULEMON ATHLETICA", 2500, 5655),
        "lululemon", "resolved",
    )
    with_groups = resolve_status(lululemon, [charge], date(2026, 5, 31), merchant_groups=merchant_groups, excluded_descriptors=excluded)
    without_groups = resolve_status(lululemon, [charge], date(2026, 5, 31), merchant_groups={}, excluded_descriptors=excluded)
    assert with_groups.status == "partially_used" and with_groups.used_minor == 2500
    assert without_groups.status == "unused"

    # Known-untrackable benefits surface as deferred with the missing source named.
    points = Benefit("amex_test_points", "amex_platinum", "calendar_year", None, missing_data_source="rewards points ledger")
    deferred = resolve_status(points, [], date(2026, 5, 31), merchant_groups=merchant_groups, excluded_descriptors=excluded)
    assert deferred.status == "deferred"
    assert deferred.reason_codes == ("non_observable_benefit",)
    assert any(value == "missing_source:rewards points ledger" for value in deferred.evidence_ids)
    assert deferred.remaining_minor is None and deferred.deadline is None

    # Frozen coverage manifest records the split and omissions.
    coverage = json.loads((ROOT / "data/frozen/terms/coverage.json").read_text())
    assert coverage["frozen_benefit_types"] == 10
    assert set(coverage["trackable_merchant_groups"]) == set(merchant_groups)

    # Real classification is local-only; verify it when present.
    classification_path = ROOT / "data/real/derived/registry/benefit-classification.json"
    classification_note = "absent"
    if classification_path.exists():
        classification = json.loads(classification_path.read_text())
        rows = classification["benefits"]
        tallies = classification["tallies"]
        assert len(rows) == tallies["total_real_benefits"] == 82
        assert all(row["benefit_id"] and row["disposition"] in {"supported", "indeterminate", "known_untrackable"} for row in rows)
        assert all("merchant_group" in row for row in rows if row["disposition"] == "supported")
        assert all(row.get("missing_data_source") for row in rows if row["disposition"] == "known_untrackable")
        observed = {row["disposition"] for row in rows}
        assert observed == {"supported", "indeterminate", "known_untrackable"}
        assert sum(row["disposition"] == "supported" for row in rows) == tallies["supported"] == 15
        assert sum(row["disposition"] == "indeterminate" for row in rows) == tallies["indeterminate"] == 2
        assert sum(row["disposition"] == "known_untrackable" for row in rows) == tallies["known_untrackable"] == 65
        classification_note = "verified"

    print("dataset_version: slice25-2026-09-20.v1")
    print(f"trackable_benefit_types: {len(benefits)}")
    print(f"merchant_groups: {len(merchant_groups)}")
    print("data_driven_matching: pass")
    print("deferred_surface: pass")
    print(f"real_classification: {classification_note}")
    print("observed_failures: []")
    print("known_coverage_gaps: real clause extraction (VKU-17); real enrollment/portal evidence remain local-only")


if __name__ == "__main__":
    main()
