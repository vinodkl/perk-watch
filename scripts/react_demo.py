#!/usr/bin/env python3
"""Offline VKU-14 smoke demo using deterministic facts and no network."""
from datetime import date
import json
import sys

sys.path.insert(0, "src")

from perk_watch.benefits import StatusResult
from perk_watch.react import ReActRuntime, ScriptedModel


def main() -> None:
    facts = [StatusResult("unused", ("no_eligible_transactions",), ("benefit:demo_monthly",), 0, 2500, date(2026, 9, 30))]
    runtime = ReActRuntime(
        question="What benefits should I use before month-end?", as_of=date(2026, 9, 20),
        evaluate=lambda as_of: facts,
        retrieve_official=lambda query, question, benefit_ids, as_of: [{
            "clause_id": "demo-clause", "citation": "synthetic-guide#demo",
            "clause_text": "Demo benefit expires at month-end.", "terms_version": "demo-v1",
        }],
    )
    print(json.dumps(runtime.run(ScriptedModel()).model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
