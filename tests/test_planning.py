from datetime import date
import unittest

from perk_watch.planning import BenefitFacts, CandidateAction, plan_benefits
from perk_watch.react import Citation


class PlanningSmokeTest(unittest.TestCase):
    def test_isolated_official_research_and_hard_feasibility(self):
        facts = [
            BenefitFacts(benefit_id="hotel", status="unused", remaining_minor=10000,
                         deadline=date(2026, 9, 30), evidence_ids=("benefit:hotel",),
                         constraints={"booking_channel": "portal"}),
            BenefitFacts(benefit_id="dining", status="unused", remaining_minor=2500,
                         deadline=date(2026, 9, 30), evidence_ids=("benefit:dining",)),
        ]
        clauses = {
            "hotel": [{"clause_id": "c-hotel"}],
            "dining": [{"clause_id": "c-dining"}],
        }

        def researcher(item, governing):
            self.assertTrue(all(row["clause_id"].endswith(item.benefit_id) for row in governing))
            return [CandidateAction(
                benefit_id=item.benefit_id, action=f"use {item.benefit_id}", value_minor=5000,
                booking_channel="wrong" if item.benefit_id == "hotel" else None,
                citations=(Citation(clause_id=governing[0]["clause_id"], citation="guide", clause_text="official"),),
            )]

        result = plan_benefits(facts, clauses, researcher, as_of=date(2026, 9, 20))
        self.assertEqual(result.actions, [])
        self.assertEqual({item.reason for item in result.dropped}, {"violates_booking_channel", "exceeds_remaining_value"})
        self.assertFalse(result.community["available"])


if __name__ == "__main__":
    unittest.main()
