#!/usr/bin/env python3
"""Interactive PerkWatch demo over prepared local data."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from local_real_data_integration import (AS_OF, _benefit_id, build_offline_retriever,
    clauses_by_benefit, dedupe, researcher)
from perk_watch.benefits import evaluate_persisted_benefits
from perk_watch.community_rag import load_served_ideas, serve_community
from perk_watch.planning import BenefitFacts, plan_benefits
from perk_watch.raw_data import data_root
from perk_watch.react import OpenAIModel, ReActRuntime, ScriptedModel
from perk_watch.rule_registry import SQLiteRuleRegistry
from perk_watch.transactions import SQLiteLedger


def run(question: str, *, scripted: bool = False, model: str = "gpt-4o-mini", as_of: date = AS_OF) -> dict:
    root = data_root()
    current = json.loads((root / "prepared/benefits/current.json").read_text())
    terms_version = current["terms_version"]
    mapping = json.loads((root / "derived/registry/benefit-classification.json").read_text())
    registry_path = root / "prepared/rules/registry.sqlite3"
    ledger = SQLiteLedger(root)
    registry = SQLiteRuleRegistry(path=registry_path)
    active = registry.active_benefits()
    groups = {row.merchant_group: {row.merchant_group} for row in active if row.merchant_group}
    with sqlite3.connect(ledger.path) as connection:
        unknown = frozenset(row[0] for row in connection.execute("select descriptor from merchant_decisions where resolution_status='indeterminate'"))
    enrolled = {row.benefit_id: True for row in active if row.enrollment_required}

    def evaluate(point):
        return dedupe(evaluate_persisted_benefits(registry_path, ledger, point, enrolled=enrolled,
            portal_confirmed={}, merchant_groups=groups, excluded_descriptors=unknown))

    metadata = json.loads((root / "prepared/indexes/official/metadata.json").read_text())["clauses"]
    official = build_offline_retriever(type("M", (), {"rows": mapping["benefits"], "by_benefit_id": {r["benefit_id"]: r for r in mapping["benefits"]}})(), metadata, terms_version)
    ideas = load_served_ideas(sorted((root / "prepared/community").glob("*/current.json")))
    community = lambda ids: serve_community(ideas, benefit_ids=ids, terms_version=terms_version)
    runtime = ReActRuntime(question=question, as_of=as_of, evaluate=evaluate,
        retrieve_official=official, retrieve_community=community, max_steps=24)
    answer = runtime.run(ScriptedModel() if scripted else OpenAIModel(model=model))
    facts = [BenefitFacts(benefit_id=_benefit_id(row), status=row.status,
        remaining_minor=row.remaining_minor if row.status in {"unused", "partially_used", "fully_used"} else None,
        deadline=row.deadline if row.status in {"unused", "partially_used", "fully_used"} else None,
        evidence_ids=(f"benefit:{_benefit_id(row)}",)) for row in evaluate(as_of)]
    plan = plan_benefits(facts, clauses_by_benefit(type("M", (), {"rows": mapping["benefits"]})(), metadata), researcher, as_of=as_of)
    return {"answer": answer.model_dump(mode="json"), "planner": plan.model_dump(mode="json"),
            "authority": "model selects tools; deterministic evaluator owns status, amounts, remaining value, deadlines, and eligibility",
            "merchant_fallback": {"unresolved_descriptor_count": len(unknown), "risk": "may cause false-unused results"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="question to ask")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--scripted", action="store_true", help="offline smoke mode")
    args = parser.parse_args()
    question = args.question or input("PerkWatch question: ")
    print(json.dumps(run(question, scripted=args.scripted, model=args.model), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
