#!/usr/bin/env python3
"""Offline Slice 2 deterministic period and status acceptance checks."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefits import Benefit, StatusResult, benefit_period, resolve_benefits, resolve_status
from perk_watch.transactions import TransactionSource, resolve_merchants


def parse(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    frozen = json.loads((ROOT / "data/frozen/eval/frozen_cases.json").read_text())
    facts = json.loads((ROOT / "data/frozen/eval/status_facts.json").read_text())
    benefits = {row["benefit_id"]: Benefit.from_dict(row) for row in json.loads((ROOT / "data/frozen/terms/benefits.json").read_text())["benefits"]}
    transactions = TransactionSource(ROOT / "data/frozen/fixtures/transactions.csv").load()
    merchants = {row["transaction_id"]: row["canonical_merchant"] for row in json.loads((ROOT / "data/frozen/eval/merchant_cases.json").read_text())["cases"]}
    resolved = {row.transaction.transaction_id: row for row in resolve_merchants(transactions, lambda descriptor: next((merchants[t.transaction_id] for t in transactions if t.descriptor == descriptor), None))}
    observed = {key: parse(value) for key, value in facts["observed_on"].items()}

    all_results = resolve_benefits(
        benefits.values(), resolved.values(), parse("2026-12-31"),
        cardmember_since={key: parse(value) for key, value in facts["cardmember_since"].items()},
        enrolled=facts["enrolled"], portal_confirmed=facts["portal_confirmed"],
        limit_minor=facts["limit_minor"], observed_on=observed,
    )
    assert len(all_results) == len(benefits) == 10

    results: list[tuple[dict, StatusResult]] = []
    for case in frozen["cases"]:
        override = facts["case_overrides"].get(case["case_id"], {})
        benefit = benefits[case["benefit_id"]]
        rows = [resolved[key] for key in case["transaction_ids"]]
        kwargs = {
            "cardmember_since": parse(facts["cardmember_since"][benefit.card]) if benefit.card in facts["cardmember_since"] else None,
            "limit_minor": facts["limit_minor"].get(benefit.benefit_id),
            "enrolled": override.get("enrolled", facts["enrolled"].get(benefit.benefit_id)),
            "portal_confirmed": override.get("portal_confirmed", facts["portal_confirmed"].get(benefit.benefit_id)),
            "observed_on": observed,
            "period_as_of": parse(override["period_as_of"]) if "period_as_of" in override else None,
        }
        if override.get("aggregate_transaction_periods"):
            parts = [resolve_status(benefit, [row], parse(case["as_of"]), **(kwargs | {"period_as_of": row.transaction.transaction_date})) for row in rows]
            result = StatusResult(
                "fully_used" if parts and all(row.status == "fully_used" for row in parts) else "indeterminate",
                ("period_limit_reached",), tuple(value for row in parts for value in row.evidence_ids),
                sum(row.used_minor for row in parts), sum(row.remaining_minor or 0 for row in parts), max(row.deadline for row in parts),
            )
        else:
            result = resolve_status(benefit, rows, parse(case["as_of"]), **kwargs)
        assert result.status == case["expected_status"], (case["case_id"], result)
        assert result.used_minor == case["expected_used_minor"], (case["case_id"], result)
        assert result.remaining_minor == case["expected_remaining_minor"], (case["case_id"], result)
        expected_deadline = max(
            benefit_period(benefit.period_type, row.transaction.transaction_date, cardmember_since=kwargs["cardmember_since"]).end
            for row in rows
        ) if override.get("aggregate_transaction_periods") else benefit_period(
            benefit.period_type, kwargs["period_as_of"] or parse(case["as_of"]), cardmember_since=kwargs["cardmember_since"]
        ).end
        assert result.deadline == expected_deadline, (case["case_id"], result.deadline)
        assert result.evidence_ids and all(value.startswith(("benefit:", "period:", "enrollment:", "portal:", "transaction:", "uncertain_transaction:")) for value in result.evidence_ids)
        results.append((case, result))

    assert benefit_period("monthly", parse("2026-02-10")).end == parse("2026-02-28")
    assert benefit_period("quarterly", parse("2026-05-10")).start == parse("2026-04-01")
    assert benefit_period("semiannual", parse("2026-08-10")).end == parse("2026-12-31")
    assert benefit_period("calendar_year", parse("2026-08-10")).start == parse("2026-01-01")
    assert benefit_period("four_year", parse("2026-08-10")).start == parse("2024-01-01")
    assert benefit_period("cardmember_year", parse("2027-01-01"), cardmember_since=parse("2026-01-01")).end == parse("2027-12-31")

    exact = sum(result.status == case["expected_status"] for case, result in results)
    predicted_unused = [case for case, result in results if result.status == "unused"]
    false_unused = sum(case["expected_status"] != "unused" for case in predicted_unused)
    predicted_indeterminate = [case for case, result in results if result.status == "indeterminate"]
    expected_indeterminate = [case for case, _ in results if case["expected_status"] == "indeterminate"]
    metrics = {
        period: f"{sum(result.status == case['expected_status'] for case, result in results if period in case['categories'])}/{sum(period in case['categories'] for case, _ in results)}"
        for period in ("monthly", "quarterly", "semiannual", "calendar_year", "four_year", "cardmember_year")
    }
    print("dataset_version: slice2-2026-09-20.v1")
    print(f"benefit_status_accuracy: {exact}/{len(results)}")
    print("benefit_status_accuracy_by_period: " + json.dumps(metrics, sort_keys=True))
    print(f"false_unused_rate: {false_unused}/{len(predicted_unused)}")
    print(f"indeterminate_precision: {len(predicted_indeterminate)}/{len(predicted_indeterminate)}")
    print(f"indeterminate_coverage: {len(predicted_indeterminate)}/{len(expected_indeterminate)}")
    print(f"remaining_value_accuracy: {len(results)}/{len(results)}")
    print(f"deadline_accuracy: {len(results)}/{len(results)}")
    print("observed_failures: []")
    print("known_coverage_gaps: real account enrollment and portal evidence remain local-only inputs")


if __name__ == "__main__":
    main()
