#!/usr/bin/env python3
"""Offline VKU-19 demo: isolated official-clause researchers and hard filtering."""
from datetime import date
import json
import sys

sys.path.insert(0, "src")

from perk_watch.planning import BenefitFacts, CandidateAction, plan_benefits
from perk_watch.react import Citation


def researcher(facts, clauses):
    clause = clauses[0]
    if facts.benefit_id == "hotel":
        action = CandidateAction(
            benefit_id="hotel", action="Book a prepaid hotel through the portal", value_minor=25000,
            booking_channel="portal", deadline=date(2026, 9, 30),
            evidence_ids=("benefit:hotel",),
            citations=(Citation(clause_id=clause["clause_id"], citation="guide#hotel", clause_text=clause["text"]),),
        )
    else:
        action = CandidateAction(
            benefit_id="airline", action="Buy an excluded airfare", value_minor=15000,
            booking_channel="airline", deadline=date(2026, 9, 30),
            evidence_ids=("benefit:airline",),
            citations=(Citation(clause_id=clause["clause_id"], citation="guide#airline", clause_text=clause["text"]),),
        )
    return [action]


def main():
    result = plan_benefits(
        [
            BenefitFacts(benefit_id="hotel", status="unused", remaining_minor=30000, deadline=date(2026, 9, 30), evidence_ids=("benefit:hotel",)),
            BenefitFacts(benefit_id="airline", status="unused", remaining_minor=10000, deadline=date(2026, 9, 30), evidence_ids=("benefit:airline",)),
        ],
        {"hotel": [{"clause_id": "c-hotel", "text": "Prepaid portal hotel booking."}],
         "airline": [{"clause_id": "c-airline", "text": "Selected-airline incidental fees; airfare excluded."}]},
        researcher, as_of=date(2026, 9, 20),
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
