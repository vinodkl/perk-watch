#!/usr/bin/env python3
"""Inventory and validate the local-only VKU-27 dataset without exporting records."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from perk_watch.raw_data import data_root, source_records


def _load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _dataset_version(root: Path, terms_version: str, sources: list[dict]) -> str:
    value = json.dumps({"terms_version": terms_version, "sources": sorted(
        (row.get("card_id"), row.get("kind"), row.get("content_sha256")) for row in sources
    )}, separators=(",", ":"), sort_keys=True).encode()
    return "local-vku27-" + hashlib.sha256(value).hexdigest()[:16]


def _metrics(cases: list[dict], predictions: dict[str, dict]) -> dict:
    if not cases or any(case["case_id"] not in predictions for case in cases):
        return {name: None for name in (
            "benefit_status_accuracy", "false_unused_rate", "indeterminate_precision",
            "indeterminate_coverage", "remaining_value_accuracy", "deadline_accuracy",
            "merchant_match_accuracy",
        )}
    expected = [case.get("expected", case) for case in cases]
    observed = [predictions[case["case_id"]] for case in cases]
    equal = lambda key: sum(a.get(key) == b.get("expected_" + key) for a, b in zip(observed, expected))
    return {
        "benefit_status_accuracy": f"{equal('status')}/{len(cases)}",
        "false_unused_rate": None,
        "indeterminate_precision": None,
        "indeterminate_coverage": None,
        "remaining_value_accuracy": f"{equal('remaining_minor')}/{len(cases)}",
        "deadline_accuracy": f"{equal('deadline')}/{len(cases)}",
        "merchant_match_accuracy": None,
    }


def main() -> None:
    root = data_root()
    sources = source_records(root)
    current = _load(root / "prepared/benefits/current.json", {})
    terms_version = str(current.get("terms_version") or "unavailable")
    cases_doc = _load(root / "prepared/evaluation/local_cases.json", {})
    cases = cases_doc.get("cases", [])
    categories = Counter(category for case in cases for category in case.get("categories", []))
    ledger_path = root / "prepared/transactions/ledger.sqlite3"
    registry_path = root / "prepared/rules/registry.sqlite3"
    ledger = sqlite3.connect(ledger_path) if ledger_path.exists() else None
    registry = sqlite3.connect(registry_path) if registry_path.exists() else None
    tx_count = ledger.execute("select count(*) from transactions").fetchone()[0] if ledger else 0
    merchant_total = ledger.execute("select count(*) from merchant_decisions").fetchone()[0] if ledger else 0
    merchant_resolved = ledger.execute("select count(*) from merchant_decisions where resolution_status='resolved'").fetchone()[0] if ledger else 0
    active_rules = registry.execute("select count(*) from active_rules").fetchone()[0] if registry else 0
    dataset_version = _dataset_version(root, terms_version, sources)
    manifest = {
        "dataset": "local-real-data-validation-vku-27",
        "dataset_version": dataset_version,
        "synthetic": False,
        "terms_version": terms_version,
        "source_hashes": sorted(row.get("content_sha256") for row in sources),
        "case_count": len(cases),
        "category_counts": dict(sorted(categories.items())),
    }
    report = {
        "dataset": manifest,
        "human_labels": "available" if cases else "unavailable",
        "runtime_decisions": "automated deterministic harness only",
        "inventory": {
            "transaction_count": tx_count,
            "merchant_decision_count": merchant_total,
            "merchant_resolved_count": merchant_resolved,
            "active_rule_count": active_rules,
        },
        "metrics": _metrics(cases, {}),
        "observed_failures": [],
        "known_coverage_gaps": [
            "Human-labelled local cases are absent; no local accuracy numerator/denominator is claimed.",
            "No active deterministic rules are present in the local registry; local status/value/deadline evaluation is unavailable until VKU-17 supplies rules.",
            "Merchant counts describe prepared resolution coverage only, not labelled merchant-match accuracy.",
            "Unavailable categories and period types are not substituted with synthetic cases.",
        ],
    }
    output = root / "prepared/evaluation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "vku-27-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output / "vku-27-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
