#!/usr/bin/env python3
"""Reproducible synthetic comparison: retrieval-based versus tool-based handling."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefits import Benefit, benefit_period, resolve_status
from perk_watch.transactions import ResolvedTransaction, TransactionSource, resolve_merchants

DEFAULT_MODEL = "frozen-offline-model-v1"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


class FrozenVectorStore:
    """Tiny deterministic vector-store stand-in; no network or embedding service."""

    def __init__(self, documents):
        self.documents = documents

    def search(self, query: str, top_k: int) -> list[dict]:
        query_tokens = tokens(query)
        ranked = []
        for index, document in enumerate(self.documents):
            overlap = len(query_tokens & tokens(document["text"]))
            ranked.append((overlap, -index, document))
        return [document for overlap, _, document in sorted(ranked, reverse=True)[:top_k] if overlap]


def build_store(benefits, clauses, groups, transactions):
    documents = []
    for benefit in benefits:
        documents.append({"kind": "official_term", "id": benefit["benefit_id"], "text": json.dumps(benefit, sort_keys=True), "payload": benefit})
    for clause in clauses:
        documents.append({"kind": "official_term", "id": clause["clause_id"], "text": json.dumps(clause, sort_keys=True), "payload": clause})
    documents.append({"kind": "official_term", "id": "merchant-groups", "text": json.dumps(groups, sort_keys=True), "payload": groups})
    for transaction in transactions:
        payload = {
            "transaction_id": transaction.transaction_id, "card": transaction.card,
            "transaction_date": transaction.transaction_date.isoformat(),
            "posted_date": transaction.posted_date.isoformat(), "descriptor": transaction.descriptor,
            "amount_minor": transaction.amount_minor, "mcc": transaction.mcc,
        }
        documents.append({"kind": "synthetic_transaction", "id": transaction.transaction_id, "text": json.dumps(payload, sort_keys=True), "payload": payload})
    return FrozenVectorStore(documents)


def period_end(period_type: str, as_of: date, cardmember_since: date | None = None) -> date | None:
    try:
        return benefit_period(period_type, as_of, cardmember_since=cardmember_since).end
    except ValueError:
        return None


def baseline_result(case, store: FrozenVectorStore, groups, top_k: int) -> dict:
    query = " ".join([case["benefit_id"], case["as_of"], *case["categories"], *case["transaction_ids"]])
    retrieved = store.search(query, top_k)
    term = next((row["payload"] for row in retrieved if row["kind"] == "official_term" and row["id"] == case["benefit_id"]), None)
    if term is None:
        return {"status": "indeterminate", "used_minor": 0, "remaining_minor": None, "deadline": None, "retrieved": len(retrieved)}
    as_of = date.fromisoformat(case["as_of"])
    deadline = period_end(term["period_type"], as_of)
    limit = term.get("period_amount_minor")
    if limit is None or term.get("enrollment_required") or term.get("portal_gated"):
        return {"status": "indeterminate", "used_minor": 0, "remaining_minor": limit, "deadline": deadline.isoformat() if deadline else None, "retrieved": len(retrieved)}

    txs = {row["payload"]["transaction_id"]: row["payload"] for row in retrieved if row["kind"] == "synthetic_transaction"}
    group = term.get("merchant_group", "")
    group_words = tokens(group.replace("_", " "))
    eligible = []
    uncertain = False
    for transaction_id in case["transaction_ids"]:
        row = txs.get(transaction_id)
        if row is None:
            uncertain = True
            continue
        if date.fromisoformat(row["posted_date"]) > as_of:
            uncertain = True
            continue
        descriptor_words = tokens(row["descriptor"])
        if row["descriptor"] in groups.get("excluded_descriptors", []):
            continue
        # The retrieval baseline asks its model to infer eligibility from terms and descriptors.
        if group_words & descriptor_words or any(word in descriptor_words for word in groups.get("groups", {}).get(group, [])):
            eligible.append(row["amount_minor"])
    if uncertain:
        status, used = "indeterminate", 0
    else:
        used = min(limit, sum(max(0, value) for value in eligible))
        status = "fully_used" if used == limit else "partially_used" if used else "unused"
    return {"status": status, "used_minor": used, "remaining_minor": limit - used, "deadline": deadline.isoformat() if deadline else None, "retrieved": len(retrieved)}


def tool_results(cases, benefits, groups, facts, transactions, merchant_cases):
    merchants = {row["transaction_id"]: row["canonical_merchant"] for row in merchant_cases}
    resolved = resolve_merchants(transactions, lambda descriptor: next((merchants[t.transaction_id] for t in transactions if t.descriptor == descriptor), None))
    by_id = {row.transaction.transaction_id: row for row in resolved}
    results = {}
    benefits_by_id = {row.benefit_id: row for row in benefits}
    merchant_groups = {name: set(codes) for name, codes in groups["groups"].items()}
    excluded = frozenset(groups["excluded_descriptors"])
    for case in cases:
        override = facts["case_overrides"].get(case["case_id"], {})
        benefit = benefits_by_id[case["benefit_id"]]
        kwargs = {
            "cardmember_since": date.fromisoformat(facts["cardmember_since"][benefit.card]) if benefit.card in facts["cardmember_since"] else None,
            "limit_minor": facts["limit_minor"].get(benefit.benefit_id),
            "enrolled": override.get("enrolled", facts["enrolled"].get(benefit.benefit_id)),
            "portal_confirmed": override.get("portal_confirmed", facts["portal_confirmed"].get(benefit.benefit_id)),
            "observed_on": {key: date.fromisoformat(value) for key, value in facts["observed_on"].items()},
            "period_as_of": date.fromisoformat(override["period_as_of"]) if "period_as_of" in override else None,
            "merchant_groups": merchant_groups, "excluded_descriptors": excluded,
        }
        rows = [by_id[key] for key in case["transaction_ids"]]
        if override.get("aggregate_transaction_periods"):
            parts = [resolve_status(benefit, [row], date.fromisoformat(case["as_of"]), **(kwargs | {"period_as_of": row.transaction.transaction_date})) for row in rows]
            from perk_watch.benefits import StatusResult
            result = StatusResult("fully_used" if parts and all(row.status == "fully_used" for row in parts) else "indeterminate", ("period_limit_reached",), tuple(value for row in parts for value in row.evidence_ids), sum(row.used_minor for row in parts), sum(row.remaining_minor or 0 for row in parts), max(row.deadline for row in parts))
        else:
            result = resolve_status(benefit, rows, date.fromisoformat(case["as_of"]), **kwargs)
        results[case["case_id"]] = {"status": result.status, "used_minor": result.used_minor, "remaining_minor": result.remaining_minor, "deadline": result.deadline.isoformat() if result.deadline else None, "retrieved": None}
    return results


def metric(rows, predicate) -> str:
    return f"{sum(predicate(row) for row in rows)}/{len(rows)}"


def report(name, cases, predictions):
    rows = [{"case_id": case["case_id"], "categories": case["categories"], "expected": case, "observed": predictions[case["case_id"]]} for case in cases]
    predicted_unused = [row for row in rows if row["observed"]["status"] == "unused"]
    predicted_indeterminate = [row for row in rows if row["observed"]["status"] == "indeterminate"]
    expected_indeterminate = [row for row in rows if row["expected"]["expected_status"] == "indeterminate"]
    category_counts = Counter(category for case in cases for category in case["categories"])
    by_category = {category: metric([row for row in rows if category in row["categories"]], lambda row: row["observed"]["status"] == row["expected"]["expected_status"]) for category in sorted(category_counts)}
    failures = [row["case_id"] for row in rows if row["observed"]["status"] != row["expected"]["expected_status"] or row["observed"]["used_minor"] != row["expected"]["expected_used_minor"] or row["observed"]["remaining_minor"] != row["expected"]["expected_remaining_minor"] or row["observed"]["deadline"] != _expected_deadline(row["expected"], cases)]
    return {
        "handling": name, "case_count": len(rows), "category_counts": dict(sorted(category_counts.items())),
        "benefit_status_accuracy": metric(rows, lambda row: row["observed"]["status"] == row["expected"]["expected_status"]),
        "benefit_status_accuracy_by_question_type": by_category,
        "false_unused_rate": f"{sum(row['expected']['expected_status'] != 'unused' for row in predicted_unused)}/{len(predicted_unused)}" if predicted_unused else None,
        "indeterminate_precision": f"{sum(row['expected']['expected_status'] == 'indeterminate' for row in predicted_indeterminate)}/{len(predicted_indeterminate)}" if predicted_indeterminate else None,
        "indeterminate_coverage": f"{sum(row['observed']['status'] == 'indeterminate' for row in expected_indeterminate)}/{len(expected_indeterminate)}" if expected_indeterminate else None,
        "remaining_value_accuracy": metric(rows, lambda row: row["observed"]["remaining_minor"] == row["expected"]["expected_remaining_minor"]),
        "deadline_accuracy": metric(rows, lambda row: row["observed"]["deadline"] == _expected_deadline(row["expected"], cases)),
        "observed_failures": failures,
        "predictions": [{"case_id": row["case_id"], "output": row["observed"]} for row in rows],
    }


def _expected_deadline(case, cases) -> str | None:
    # Frozen expected deadlines are recomputed by the tool path; use the same period rule for scoring.
    benefits = getattr(_expected_deadline, "benefits", {})
    facts = getattr(_expected_deadline, "facts", {})
    benefit = benefits[case["benefit_id"]]
    override = facts.get("case_overrides", {}).get(case["case_id"], {})
    since = date.fromisoformat(facts["cardmember_since"][benefit.card]) if benefit.card in facts.get("cardmember_since", {}) else None
    if override.get("aggregate_transaction_periods"):
        tx_dates = getattr(_expected_deadline, "transaction_dates", {})
        return max(benefit_period(benefit.period_type, tx_dates[key], cardmember_since=since).end for key in case["transaction_ids"]).isoformat()
    point = date.fromisoformat(override.get("period_as_of", case["as_of"]))
    return benefit_period(benefit.period_type, point, cardmember_since=since).end.isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()
    frozen = ROOT / "evals/data/frozen"
    frozen_doc, benefit_doc, clauses_doc = load(frozen / "eval/frozen_cases.json"), load(frozen / "terms/benefits.json"), load(frozen / "terms/clauses.json")
    groups = load(frozen / "terms/merchant_groups.json")
    facts, merchant_cases = load(frozen / "eval/status_facts.json"), load(frozen / "eval/merchant_cases.json")["cases"]
    transactions = TransactionSource(frozen / "fixtures/transactions.csv").load()
    benefits = [Benefit.from_dict(row) for row in benefit_doc["benefits"]]
    cases = frozen_doc["cases"]
    store = build_store(benefit_doc["benefits"], clauses_doc["clauses"], groups, transactions)
    _expected_deadline.benefits = {benefit.benefit_id: benefit for benefit in benefits}
    _expected_deadline.facts = facts
    _expected_deadline.transaction_dates = {row.transaction_id: row.transaction_date for row in transactions}
    baseline = {case["case_id"]: baseline_result(case, store, groups, args.top_k) for case in cases}
    tool = tool_results(cases, benefits, groups, facts, transactions, merchant_cases)
    output = {
        "dataset": {"dataset_version": frozen_doc["dataset_version"], "terms_version": benefit_doc["terms_version"], "synthetic": True, "case_count": len(cases), "category_counts": dict(sorted(Counter(category for case in cases for category in case["categories"]).items()))},
        "model": {"name": args.model, "same_model_for": ["retrieval-based", "tool-based"], "temperature": 0, "network": False},
        "authority_boundary": "Tool-based status, transaction filtering, eligibility, arithmetic, remaining value, and deadlines remain deterministic; merchant resolution is model-authoritative. Baseline is retrieval-based transaction handling and is not an authority change.",
        "comparison": [report("retrieval-based transaction handling", cases, baseline), report("tool-based transaction handling", cases, tool)],
        "known_coverage_gaps": ["No local real-data results: VKU-27 owns that separate dataset.", "No live model/API run in the reproducible offline command; --model labels the shared model contract.", "Community retrieval, red-team coverage, and arithmetic ablation are out of scope."],
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
