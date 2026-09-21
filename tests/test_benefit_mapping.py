from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from perk_watch.benefit_mapping import (
    REVIEWED_FILENAME,
    annotate_clauses,
    build_draft_mapping,
    clause_slug,
    load_benefit_mapping,
    registry_dir,
)
from perk_watch.rule_registry import SQLiteRuleRegistry


def amex_clause(key: str) -> dict:
    source_id = "amex_platinum:https://example.com/guide"
    return {
        "clause_id": f"{source_id}:{key}",
        "source_id": source_id,
        "benefit_id": None,
        "terms_version": "t1",
        "effective_from": None,
        "effective_to": None,
        "text": "up to $25 each month.",
    }


class BenefitMappingTest(unittest.TestCase):
    def test_clause_slug_strips_source_and_index(self):
        clause = amex_clause("120-uber-one-credit-001")
        self.assertEqual(clause_slug(clause), "120-uber-one-credit")
        chase = {
            "clause_id": "chase_sapphire_preferred:https://example.com/hub:chunk-047",
            "source_id": "chase_sapphire_preferred:https://example.com/hub",
        }
        self.assertEqual(clause_slug(chase), "chunk")

    def test_draft_is_never_reviewed_or_active(self):
        clauses = [
            amex_clause("200-airline-fee-credit-001"),
            amex_clause("200-airline-fee-credit-002"),
            {
                "clause_id": "chase_sapphire_preferred:https://example.com/hub:chunk-001",
                "source_id": "chase_sapphire_preferred:https://example.com/hub",
                "benefit_id": None,
                "terms_version": "t1",
                "text": "prose",
            },
        ]
        draft = build_draft_mapping(clauses, "t1")
        self.assertFalse(draft["reviewed"])
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["tallies"], {
            "total_real_benefits": 2, "supported": 0, "indeterminate": 2, "known_untrackable": 0,
        })
        self.assertTrue(all(row["disposition"] == "indeterminate" for row in draft["benefits"]))
        self.assertEqual({row["clause_slug"] for row in draft["benefits"]}, {"200-airline-fee-credit", "chunk"})
        proposed_fields = {
            "benefit_id", "card", "period_type", "period_amount_minor", "eligibility",
            "enrollment_required", "portal_gated", "effective_from", "effective_to",
            "governing_clause_ids",
        }
        self.assertTrue(all(proposed_fields <= row.keys() for row in draft["benefits"]))

    def test_load_refuses_unreviewed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = registry_dir(root) / REVIEWED_FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"reviewed": False, "benefits": []}))
            with self.assertRaises(ValueError):
                load_benefit_mapping(root, require_reviewed=True)
            self.assertFalse(load_benefit_mapping(root, require_reviewed=False).reviewed)
            # No file at all -> empty mapping, no error.
            self.assertFalse(load_benefit_mapping(Path(directory) / "empty").reviewed)

    def test_annotate_only_supported_rows(self):
        clauses = [amex_clause("120-uber-one-credit-001"), amex_clause("200-airline-fee-credit-001")]
        document = {
            "reviewed": True,
            "benefits": [
                {
                    "benefit_id": "amex_platinum_uber_one", "card": "amex_platinum",
                    "clause_slug": "120-uber-one-credit", "disposition": "supported",
                    "period_type": "monthly", "period_amount_minor": 1500,
                    "merchant_group": "uber",
                    "governing_clause_ids": [
                        "amex_platinum:https://example.com/guide:120-uber-one-credit-001",
                    ],
                },
                {
                    "benefit_id": "amex_platinum_airline_fee", "card": "amex_platinum",
                    "clause_slug": "200-airline-fee-credit", "disposition": "known_untrackable",
                    "missing_data_source": "statement credit ledger",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = registry_dir(root) / REVIEWED_FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document))
            mapping = load_benefit_mapping(root, require_reviewed=True)
            annotated = {c["clause_id"]: c for c in annotate_clauses(clauses, mapping)}
            uber = annotated["amex_platinum:https://example.com/guide:120-uber-one-credit-001"]
            self.assertEqual(uber["benefit_id"], "amex_platinum_uber_one")
            self.assertEqual(uber["period_type"], "monthly")
            self.assertEqual(uber["period_amount_minor"], 1500)
            self.assertEqual(uber["eligibility"], {"merchant_group": "uber"})
            airline = annotated["amex_platinum:https://example.com/guide:200-airline-fee-credit-001"]
            self.assertIsNone(airline["benefit_id"])  # untrackable rows never annotate clauses

    def test_reviewed_mapping_ingests_only_supported(self):
        clauses = [amex_clause("120-uber-one-credit-001"), amex_clause("200-airline-fee-credit-001")]
        document = {
            "reviewed": True,
            "benefits": [
                {
                    "benefit_id": "amex_platinum_uber_one", "card": "amex_platinum",
                    "clause_slug": "120-uber-one-credit", "disposition": "supported",
                    "period_type": "monthly", "period_amount_minor": 1500,
                    "merchant_group": "uber",
                    "governing_clause_ids": [
                        "amex_platinum:https://example.com/guide:120-uber-one-credit-001",
                    ],
                },
                {
                    "benefit_id": "amex_platinum_airline_fee", "card": "amex_platinum",
                    "clause_slug": "200-airline-fee-credit", "disposition": "known_untrackable",
                    "missing_data_source": "statement credit ledger",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = registry_dir(root) / REVIEWED_FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document))
            mapping = load_benefit_mapping(root, require_reviewed=True)
            registry = SQLiteRuleRegistry(path=root / "registry.sqlite3")
            result = registry.ingest(annotate_clauses(clauses, mapping))
            self.assertEqual(result, {"accepted": 1, "rejected": 1, "skipped": 0})
            self.assertEqual([b.benefit_id for b in registry.active_benefits()], ["amex_platinum_uber_one"])
            for row in registry.active_rule_provenance():
                self.assertEqual(row["decision_outcome"], "supported")


if __name__ == "__main__":
    unittest.main()
