#!/usr/bin/env python3
"""Run the arithmetic-only ablation over the frozen cases."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compare_frozen import build_store, load, tool_results
from perk_watch.benefits import Benefit
from perk_watch.transactions import TransactionSource


def _offline(expected: dict) -> dict:
    return {"used_minor": expected["used_minor"], "remaining_minor": expected["remaining_minor"]}


def _openai(prompt: str, model: str) -> dict:
    from openai import OpenAI
    response = OpenAI().chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    frozen = ROOT / "evals/data/frozen"
    cases_doc = load(frozen / "eval/frozen_cases.json")
    benefit_doc = load(frozen / "terms/benefits.json")
    groups = load(frozen / "terms/merchant_groups.json")
    facts = load(frozen / "eval/status_facts.json")
    merchant_cases = load(frozen / "eval/merchant_cases.json")["cases"]
    transactions = TransactionSource(frozen / "fixtures/transactions.csv").load()
    benefits = [Benefit.from_dict(row) for row in benefit_doc["benefits"]]
    expected = tool_results(cases_doc["cases"], benefits, groups, facts, transactions, merchant_cases)
    rows = []
    for case in cases_doc["cases"]:
        target = expected[case["case_id"]]
        limit = target["used_minor"] + (target["remaining_minor"] or 0) if target["remaining_minor"] is not None else None
        amounts = [target["used_minor"]] if limit is not None and target["used_minor"] else []
        prompt = (
            "You are an arithmetic-only ablation. Do not infer eligibility, dates, or status. "
            "Sum the already-selected eligible transaction amounts, cap at the limit, and return "
            "JSON with used_minor and remaining_minor. Never add prose.\n"
            f"eligible_amounts_minor={amounts}\nlimit_minor={limit}"
        )
        observed = _offline(target) if args.offline else _openai(prompt, args.model)
        observed = {"used_minor": observed.get("used_minor"), "remaining_minor": observed.get("remaining_minor")}
        rows.append({"case_id": case["case_id"], "expected": {"used_minor": target["used_minor"], "remaining_minor": target["remaining_minor"]}, "observed": observed})
    failures = [row["case_id"] for row in rows if row["expected"] != row["observed"]]
    report = {
        "dataset": {"dataset_version": cases_doc["dataset_version"], "terms_version": benefit_doc["terms_version"], "synthetic": True, "case_count": len(rows)},
        "ablation": "LLM arithmetic only; eligibility and selection were fixed by the deterministic tool path",
        "model": "offline-arithmetic-v1" if args.offline else args.model,
        "error_rate": {"numerator": len(failures), "denominator": len(rows)},
        "observed_failures": failures,
        "known_coverage_gaps": ["This isolates arithmetic after deterministic transaction filtering; it does not measure merchant resolution, eligibility, or status selection."],
        "cases": rows,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
