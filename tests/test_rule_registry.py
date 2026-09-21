from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from perk_watch.rule_registry import SQLiteRuleRegistry


def make_clause(clause_id: str, benefit_id: str | None, **overrides) -> dict:
    row = {
        "clause_id": clause_id,
        "benefit_id": benefit_id,
        "terms_version": "t1",
        "source_id": "guide",
        "text": "up to $25 each month.",
        "period_type": "monthly",
        "period_amount_minor": 2500,
        "eligibility": {"merchant_group": "test"},
    }
    row.update(overrides)
    return row


class RuleRegistrySafetyTest(unittest.TestCase):
    def test_unmapped_clause_cannot_activate(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRuleRegistry(path=Path(directory) / "registry.sqlite3")
            result = registry.ingest([make_clause("c1", None)])
            self.assertEqual(result, {"accepted": 0, "rejected": 1, "skipped": 0})
            self.assertEqual(registry.active_benefits(), [])
            self.assertEqual(
                registry.decisions()[0]["reason"], "clause is not mapped to a benefit"
            )

    def test_missing_eligibility_cannot_activate(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRuleRegistry(path=Path(directory) / "registry.sqlite3")
            result = registry.ingest([make_clause("c1", "amex_platinum_x", eligibility=None)])
            self.assertEqual(result["accepted"], 0)
            self.assertEqual(result["rejected"], 1)
            self.assertEqual(registry.active_benefits(), [])

    def test_reviewed_mapping_retains_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRuleRegistry(path=Path(directory) / "registry.sqlite3")
            registry.ingest([make_clause("c1", "amex_platinum_x")])
            provenances = registry.active_rule_provenance()
            self.assertEqual(len(provenances), 1)
            row = provenances[0]
            self.assertEqual(row["decision_outcome"], "supported")
            self.assertEqual(row["benefit_id"], "amex_platinum_x")
            self.assertEqual(row["source_id"], "guide")
            self.assertEqual(row["decision_source_id"], "guide")
            self.assertEqual(row["decision_benefit_id"], "amex_platinum_x")
            self.assertEqual(row["terms_version"], "t1")
            proposal = json.loads(row["decision_proposal_json"])
            self.assertEqual(proposal["benefit_id"], "amex_platinum_x")
            self.assertEqual(proposal["period_amount_minor"], 2500)
            self.assertEqual(proposal["eligibility"]["merchant_group"], "test")

    def test_active_rules_always_have_supported_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRuleRegistry(path=Path(directory) / "registry.sqlite3")
            result = registry.ingest([
                make_clause("ok", "amex_platinum_ok"),
                make_clause("bad", "amex_platinum_bad", eligibility=None),
                make_clause("unmapped", None),
            ])
            self.assertEqual(result, {"accepted": 1, "rejected": 2, "skipped": 0})
            self.assertEqual([b.benefit_id for b in registry.active_benefits()], ["amex_platinum_ok"])
            for row in registry.active_rule_provenance():
                self.assertEqual(row["decision_outcome"], "supported")
                self.assertEqual(row["benefit_id"], "amex_platinum_ok")

    def test_read_guard_rejects_unmapped_active_row(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = SQLiteRuleRegistry(path=Path(directory) / "registry.sqlite3")
            registry.ingest([make_clause("c1", "amex_platinum_x")])
            with registry._connect() as db:
                db.execute(
                    "INSERT INTO active_rules (clause_id, benefit_id, source_id, terms_version,"
                    " eligibility_json, enrollment_required, portal_gated)"
                    " VALUES ('hand', '', 'guide', 't1', '{}', 0, 0)"
                )
            with self.assertRaises(ValueError):
                registry.active_benefits()

    def test_restart_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.sqlite3"
            SQLiteRuleRegistry(path=path).ingest([make_clause("c1", "amex_platinum_x")])
            restarted = SQLiteRuleRegistry(path=path)
            self.assertEqual(len(restarted.active_benefits()), 1)
            result = restarted.ingest([make_clause("c1", "amex_platinum_x")])
            self.assertEqual(result, {"accepted": 0, "rejected": 0, "skipped": 1})
            self.assertEqual(len(restarted.active_benefits()), 1)


if __name__ == "__main__":
    unittest.main()
