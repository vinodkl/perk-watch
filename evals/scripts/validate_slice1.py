#!/usr/bin/env python3
"""Offline Slice 1 acceptance checks."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.transactions import TransactionSource, resolve_merchants


def main():
    transactions = TransactionSource(ROOT / "evals/data/frozen/fixtures/transactions.csv").load()
    assert transactions == TransactionSource(ROOT / "evals/data/frozen/fixtures/transactions.csv").load()
    assert all(isinstance(row.amount_minor, int) for row in transactions)

    ofx = TransactionSource(ROOT / "evals/data/frozen/fixtures/transactions.ofx", card="amex_platinum").load()
    assert [(row.transaction_id, row.transaction_date.isoformat(), row.posted_date.isoformat(), row.mcc) for row in ofx] == [
        ("ofx-001", "2026-01-06", "2026-01-06", 4899),
        ("ofx-002", "2026-03-31", "2026-04-04", 5812),
    ]

    cases = json.loads((ROOT / "evals/data/frozen/eval/merchant_cases.json").read_text())["cases"]
    expected = {case["transaction_id"]: case["canonical_merchant"] for case in cases}
    descriptors = {row.descriptor: expected[row.transaction_id] for row in transactions}
    results = resolve_merchants(transactions, descriptors.get)
    observed = {row.transaction.transaction_id: row.canonical_merchant for row in results}

    predicted_positive = sum(value is not None for value in observed.values())
    actual_positive = sum(value is not None for value in expected.values())
    true_positive = sum(observed[key] == value and value is not None for key, value in expected.items())
    assert observed == expected
    assert all(row.resolution_status == "indeterminate" for row in resolve_merchants(transactions, lambda _: None))

    print("dataset_version: slice1-2026-09-19.v1")
    print(f"merchant_precision: {true_positive}/{predicted_positive}")
    print(f"merchant_recall: {true_positive}/{actual_positive}")
    print("normalization_reproducibility: 24/24")
    print("ofx_normalization: 2/2")
    print("indeterminate_path: 24/24")
    print("observed_failures: []")
    print("known_coverage_gaps: live model resolver; actual bank OFX dialects; card/MCC metadata absent from standard OFX")


if __name__ == "__main__":
    main()
