#!/usr/bin/env python3
"""Offline Slice 0 acceptance checks. Network access is intentionally absent."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VERSION = "slice0-2026-09-19.v1"


def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def fail(message):
    raise AssertionError(message)


def main():
    benefits = load(DATA / "terms/benefits.json")
    clauses = load(DATA / "terms/clauses.json")
    served = load(DATA / "community/served_ideas.json")
    conflicts = load(DATA / "community/conflicting_ideas.json")
    frozen = load(DATA / "eval/frozen_cases.json")

    assert benefits["dataset_version"] == VERSION
    assert frozen["dataset_version"] == VERSION
    assert len(benefits["benefits"]) == 10
    benefit_ids = {b["benefit_id"] for b in benefits["benefits"]}
    assert len(benefit_ids) == 10
    assert {b["period_type"] for b in benefits["benefits"]} >= {
        "monthly", "quarterly", "semiannual", "calendar_year", "four_year", "cardmember_year"
    }

    clause_ids = {c["clause_id"] for c in clauses["clauses"]}
    assert len(clause_ids) == len(clauses["clauses"])
    assert all(c["benefit_id"] in benefit_ids and c["terms_version"] == benefits["terms_version"] for c in clauses["clauses"])
    assert all(c["synthetic"] if "synthetic" in c else True for c in clauses["clauses"])

    served_rows = served["ideas"]
    conflict_rows = conflicts["ideas"]
    assert all(row["served"] is True and row["review_label"] == "no_known_conflict" for row in served_rows)
    assert all(row["served"] is False for row in conflict_rows)
    assert not ({r["idea_id"] for r in served_rows} & {r["idea_id"] for r in conflict_rows})
    required_community = {"benefit_id", "source_date", "source_url", "excerpt", "corpus_version", "terms_version"}
    assert all(required_community <= row.keys() for row in served_rows + conflict_rows)
    assert all(row["source_url"].startswith("https://example.invalid/") for row in served_rows + conflict_rows)

    # The seeded contradiction oracle is deliberately transparent until a model checker exists.
    conflict_results = [row["review_label"].startswith("conflicts_") == row["expected_conflict"] for row in conflict_rows]
    conflict_correct = sum(conflict_results)
    conflict_total = len(conflict_results)
    assert conflict_total and conflict_correct == conflict_total

    cases = frozen["cases"]
    assert 30 <= len(cases) <= 40
    allowed = {"fully_used", "partially_used", "unused", "indeterminate"}
    counts = Counter(case["expected_status"] for case in cases)
    assert set(counts) <= allowed and set(counts) == allowed
    required_categories = {"monthly", "quarterly", "semiannual", "calendar_year", "four_year", "cardmember_year", "enrollment_required", "portal_gated", "posting_lag_boundary", "near_miss_descriptor"}
    present_categories = {category for case in cases for category in case["categories"]}
    assert required_categories <= present_categories
    assert all(case["benefit_id"] in benefit_ids and case["ground_truth"] if "ground_truth" in case else True for case in cases)
    assert all(case["expected_used_minor"] >= 0 and case["expected_remaining_minor"] >= 0 for case in cases)

    fixture_path = DATA / "fixtures/transactions.csv"
    with fixture_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(row["synthetic"] == "true" for row in rows)

    files = sorted(p for p in DATA.rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())

    print(f"dataset_version: {VERSION}")
    print(f"frozen_cases: {len(cases)}")
    print("category_counts: " + json.dumps(dict(sorted(counts.items())), sort_keys=True))
    print(f"conflict_detection_accuracy: {conflict_correct}/{conflict_total}")
    print("observed_failures: []")
    print("known_coverage_gaps: live guide verification; all-benefit account matching; model-vs-human contradiction sampling")
    print(f"reproducibility_sha256: {digest.hexdigest()}")


if __name__ == "__main__":
    main()
