#!/usr/bin/env python3
"""VKU-27 local real-data integration (unlabelled, not an accuracy benchmark).

This harness is deliberately distinct from ``scripts/validate_local.py``: it
applies an explicitly recorded owner-directed mapping and account-state
assumptions to the staged real guides, transactions, and public community
inputs, re-runs preparation so the SQLite rule registry ingests the mapping,
then drives one end-to-end status/value/deadline/citation question and one
multi-benefit planner pass using only the local registry, ledger, and
official-clause index.

Everything it writes is local-only under ``PERKWATCH_DATA_DIR``. It never
contacts an issuer, Reddit, or any embedding API, and it does not claim
human-labelled account accuracy.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.benefit_mapping import build_draft_mapping, load_benefit_mapping, registry_dir
from perk_watch.benefits import evaluate_persisted_benefits
from perk_watch.community_rag import load_served_ideas, serve_community
from perk_watch.planning import BenefitFacts, CandidateAction, plan_benefits
from perk_watch.preparation import prepare_data
from perk_watch.raw_data import data_root
from perk_watch.react import Citation, ReActRuntime, ScriptedModel
from perk_watch.rule_registry import SQLiteRuleRegistry
from perk_watch.transactions import SQLiteLedger

REVIEWED_FILENAME = "benefit-classification.json"
PRIOR_FILENAME = "benefit-classification.prior.json"
ASSUMPTION_STATUS = "reviewed_local_real_data_integration"

AS_OF = date(2026, 9, 20)
QUESTION = (
    "What is my current status, remaining value, and deadline for each mapped "
    "Amex Platinum benefit, and which governing clause supports that?"
)

# Explicit owner-directed mapping dispositions for every Amex dollar-capped benefit.
# period_amount_minor is dollars*100; period_type is an owner-directed demo assumption recorded here.
SUPPORTED: dict[str, dict] = {
    "120-uber-one-credit": {
        "period_type": "calendar_year", "period_amount_minor": 12000,
        "merchant_group": "uber-one", "enrollment_required": True, "portal_gated": False,
    },
    "200-airline-fee-credit": {
        "period_type": "calendar_year", "period_amount_minor": 20000,
        "merchant_group": "airline-incidentals", "enrollment_required": True, "portal_gated": False,
    },
    "200-oura-ring-credit": {
        "period_type": "calendar_year", "period_amount_minor": 20000,
        "merchant_group": "oura", "enrollment_required": True, "portal_gated": False,
    },
    "200-uber-cash": {
        "period_type": "monthly", "period_amount_minor": 1500,
        "merchant_group": "uber", "enrollment_required": False, "portal_gated": False,
        "note": "Modeled as $15/month; the additional $20 December bonus is not modeled.",
    },
    "219-clear-credit": {
        "period_type": "calendar_year", "period_amount_minor": 21900,
        "merchant_group": "clear", "enrollment_required": True, "portal_gated": False,
    },
    "300-digital-entertainment-credit": {
        "period_type": "monthly", "period_amount_minor": 2500,
        "merchant_group": "digital-entertainment", "enrollment_required": True, "portal_gated": False,
    },
    "300-equinox-credit": {
        "period_type": "calendar_year", "period_amount_minor": 30000,
        "merchant_group": "equinox", "enrollment_required": True, "portal_gated": False,
    },
    "300-lululemon-credit": {
        "period_type": "quarterly", "period_amount_minor": 7500,
        "merchant_group": "lululemon", "enrollment_required": True, "portal_gated": False,
    },
    "300-soulcycle-at-home-bike-credit": {
        "period_type": "calendar_year", "period_amount_minor": 30000,
        "merchant_group": "soulcycle", "enrollment_required": True, "portal_gated": False,
    },
    "400-resy-credit": {
        "period_type": "quarterly", "period_amount_minor": 10000,
        "merchant_group": "resy", "enrollment_required": True, "portal_gated": False,
    },
    "600-hotel-credit": {
        "period_type": "semiannual", "period_amount_minor": 30000,
        "merchant_group": "amex-travel-hotel", "enrollment_required": False, "portal_gated": False,
    },
    "walmart-monthly-membership-credit": {
        "period_type": "monthly", "period_amount_minor": 1295,
        "merchant_group": "walmart", "enrollment_required": True, "portal_gated": False,
    },
    "fee-credit-for-global-entry-or-tsa-precheck": {
        "period_type": "four_year", "period_amount_minor": 12000,
        "merchant_group": "global-entry-tsa", "enrollment_required": False, "portal_gated": False,
    },
}

CHASE_SUPPORTED: dict[str, dict] = {
    "100-annual-chase-travel-hotel-credit": {
        "period_type": "calendar_year", "period_amount_minor": 10000,
        "merchant_group": "amex-travel-hotel", "enrollment_required": False, "portal_gated": False,
    },
    "global-entry-tsa-precheck-nexus-credit": {
        "period_type": "four_year", "period_amount_minor": 12000,
        "merchant_group": "global-entry-tsa", "enrollment_required": False, "portal_gated": False,
    },
}

CHASE_UNTRACKABLE_MARKERS = (
    "access", "assistance", "auto-rental", "baggage", "concierge", "coverage",
    "dashpass", "events", "extended-warranty", "insurance", "luggage", "membership",
    "no-foreign", "protection", "promo", "roadside", "subscription", "travel-accident",
    "trip-cancellation", "trip-delay",
)

_MISSING_SOURCES = {
    "membership": "issuer membership status portal",
    "rewards": "issuer rewards points ledger",
    "claims": "issuer claims and protection records",
    "account": "issuer account services portal",
    "travel": "issuer travel and experiences portal",
}

# Non-dollar Amex benefits are known-untrackable via the transaction ledger.
UNTRACKABLE: dict[str, str] = {
    "5x-membership-rewards-points": "rewards",
    "american-express-venue-collection": "travel",
    "amex-offers": "account",
    "amex-special-ticket-access": "travel",
    "baggage-insurance-plan": "claims",
    "car-rental-loss-and-damage-insurance": "claims",
    "car-rental-privileges": "travel",
    "cell-phone-protection": "claims",
    "creditsecure": "account",
    "cruise-privileges-program-cpp": "travel",
    "delta-sky-club-access": "membership",
    "digital-wallets": "account",
    "extended-warranty": "claims",
    "fico-score-and-insights": "account",
    "fine-hotels-resorts-program": "travel",
    "global-dining-access-by-resy": "travel",
    "hilton-honors-gold-status": "membership",
    "leaders-club-sterling-status-from-the-leading-hotels-of-the-world": "membership",
    "link-your-resy-profile": "travel",
    "marriott-bonvoy-gold-elite-status": "membership",
    "membership-rewards-program": "rewards",
    "no-foreign-transaction-fees": "account",
    "platinum-card-concierge": "account",
    "platinum-destinations-vacations": "travel",
    "platinum-member-airfares": "travel",
    "platinum-nights-by-resy": "travel",
    "premium-car-rental-protection": "claims",
    "premium-events-collection": "travel",
    "premium-global-assist-hotline": "account",
    "purchase-flexibility": "account",
    "purchase-protection": "claims",
    "return-protection": "claims",
    "send-money": "account",
    "split-purchases": "account",
    "the-american-express-global-lounge-collection": "membership",
    "the-centurion-lounge-complimentary-guest-access": "membership",
    "the-hotel-collection": "travel",
    "trip-cancellation-and-interruption-insurance": "claims",
    "trip-delay-insurance": "claims",
}

CHASE_UNRESOLVED = "chunk"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_assumption_mapping(clauses: list[dict], terms_version: str) -> dict:
    draft = build_draft_mapping(clauses, terms_version)
    rows = []
    for row in draft["benefits"]:
        slug = str(row["clause_slug"])
        spec = SUPPORTED.get(slug) or CHASE_SUPPORTED.get(slug)
        if spec is not None:
            updated = dict(row)
            updated.update({
                "disposition": "supported",
                "period_type": spec["period_type"],
                "period_amount_minor": spec["period_amount_minor"],
                "merchant_group": spec["merchant_group"],
                "eligibility": {"merchant_group": spec["merchant_group"]},
                "enrollment_required": bool(spec["enrollment_required"]),
                "portal_gated": bool(spec["portal_gated"]),
                "missing_data_source": None,
            })
        elif slug in UNTRACKABLE or any(marker in slug for marker in CHASE_UNTRACKABLE_MARKERS):
            updated = dict(row)
            updated.update({
                "disposition": "known_untrackable",
                "period_type": None,
                "period_amount_minor": None,
                "merchant_group": None,
                "eligibility": {"merchant_group": None},
                "enrollment_required": None,
                "portal_gated": None,
                "missing_data_source": _MISSING_SOURCES.get(
                    UNTRACKABLE.get(slug, "account"), "issuer account/benefit portal"
                ),
            })
        else:
            updated = dict(row)
            updated.update({
                "disposition": "indeterminate",
                "period_type": None,
                "period_amount_minor": None,
                "merchant_group": None,
                "eligibility": {},
                "enrollment_required": None,
                "portal_gated": None,
                "missing_data_source": "benefit mapping review required",
            })
        rows.append(updated)

    assumptions = {
        "mode": "local real-data integration",
        "real_inputs": {
            "official_guides": "staged real issuer guides; authoritative at recorded version/fetch date",
            "transactions": "staged real local transaction exports; evidence for this integration",
            "community": "staged real public Reddit inputs; non-authoritative",
        },
        "not_human_labelled_accuracy": True,
        "treat_every_mapped_benefit_as_available": True,
        "latest_staged_guide_is_current": True,
        "availability": "owner-directed assumption: every mapped benefit is available",
        "current_selection": "owner-directed assumption: latest staged guide version is current",
        "enrollment": (
            "owner-directed account-state assumption: benefits with enrollment_required=True "
            "are assumed enrolled (no portal/login verification was performed)"
        ),
        "portal": "owner-directed account-state assumption: portal_gated=False for mapped benefits",
        "merchant_resolution": (
            "OpenAI-backed local pass may resolve sanitized descriptors to one of "
            "the active merchant groups; low-confidence or ambiguous descriptors "
            "remain indeterminate. Amounts, dates, identifiers, and transaction "
            "rows are never sent."
        ),
        "period_amounts": {
            slug: {
                "period_type": spec["period_type"],
                "period_amount_minor": spec["period_amount_minor"],
                "merchant_group": spec["merchant_group"],
                "enrollment_required": bool(spec["enrollment_required"]),
                "portal_gated": bool(spec["portal_gated"]),
                "note": spec.get("note", "derived from guide slug/clause text"),
            }
            for slug, spec in sorted({**SUPPORTED, **CHASE_SUPPORTED}.items())
        },
        "known_untrackable_categories": {
            name: sorted(slug for slug, category in UNTRACKABLE.items() if category == name)
            for name in sorted(set(UNTRACKABLE.values()))
        },
        "chase_unresolved": (
            "Chase guide clauses are now structured individually from the local "
            "captured text; benefits without a reviewed mapping stay indeterminate."
        ),
        "metrics_unavailable": ["accuracy", "false_unused", "precision", "recall"],
    }

    return {
        "reviewed": True,
        "status": ASSUMPTION_STATUS,
        "terms_version": terms_version,
        "generated_at": f"local-real-data-integration:{terms_version}",
        "benefits": rows,
        "tallies": {
            "total_real_benefits": len(rows),
            "supported": sum(row["disposition"] == "supported" for row in rows),
            "indeterminate": sum(row["disposition"] == "indeterminate" for row in rows),
            "known_untrackable": sum(row["disposition"] == "known_untrackable" for row in rows),
        },
        "assumptions": assumptions,
    }


def _benefit_id(result) -> str:
    for evidence in result.evidence_ids:
        if evidence.startswith("benefit:"):
            return evidence.removeprefix("benefit:")
    return "unknown"


def _compact_evidence(evidence_ids) -> dict:
    key = []
    transactions = 0
    uncertain = 0
    samples = []
    for evidence in evidence_ids:
        if evidence.startswith("uncertain_transaction:"):
            uncertain += 1
            if len(samples) < 5:
                samples.append(evidence)
        elif evidence.startswith("transaction:"):
            transactions += 1
            if len(samples) < 5:
                samples.append(evidence)
        else:
            key.append(evidence)
    return {
        "key_evidence_ids": key,
        "eligible_transaction_count": transactions,
        "uncertain_transaction_count": uncertain,
        "sample_transaction_evidence": samples,
    }


def _status_dict(result) -> dict:
    return {
        "benefit_id": _benefit_id(result),
        "status": result.status,
        "reason_codes": list(result.reason_codes),
        "used_minor": result.used_minor,
        "remaining_minor": result.remaining_minor,
        "deadline": result.deadline.isoformat() if result.deadline else None,
        "evidence": _compact_evidence(result.evidence_ids),
    }


def dedupe(results):
    seen: set[str] = set()
    out = []
    for result in results:
        key = _benefit_id(result)
        if key not in seen:
            seen.add(key)
            out.append(result)
    return out


def build_offline_retriever(mapping, index_metadata, terms_version):
    by_clause = {row["clause_id"]: row for row in index_metadata}

    def retrieve(query, _question, benefit_ids, as_of):
        point = as_of.isoformat()
        citations = []
        for benefit_id in benefit_ids:
            row = mapping.by_benefit_id.get(benefit_id)
            if row is None:
                continue
            matched = []
            for clause_id in row.get("governing_clause_ids", []):
                meta = by_clause.get(clause_id)
                if meta is None:
                    continue
                if (meta.get("terms_version") or terms_version) != terms_version:
                    continue
                if meta.get("effective_from") and meta["effective_from"] > point:
                    continue
                if meta.get("effective_to") and point > meta["effective_to"]:
                    continue
                matched.append(meta)
            for meta in sorted(matched, key=lambda item: item["clause_id"])[:5]:
                citations.append({
                    "clause_id": meta["clause_id"],
                    "citation": meta["citation"],
                    "clause_text": meta["clause_text"],
                    "terms_version": meta.get("terms_version"),
                })
        return citations

    return retrieve


def clauses_by_benefit(mapping, index_metadata):
    by_clause = {row["clause_id"]: row for row in index_metadata}
    grouped = {}
    for row in mapping.rows:
        if row.get("disposition") != "supported":
            continue
        clauses = [
            {
                "clause_id": clause_id,
                "citation": by_clause[clause_id]["citation"],
                "clause_text": by_clause[clause_id]["clause_text"],
            }
            for clause_id in row.get("governing_clause_ids", [])
            if clause_id in by_clause
        ]
        grouped[row["benefit_id"]] = clauses
    return grouped


def researcher(facts, clauses):
    if not clauses:
        return []
    clause = clauses[0]
    return [CandidateAction(
        benefit_id=facts.benefit_id,
        action=f"Use {facts.benefit_id} before its period deadline",
        value_minor=min(facts.remaining_minor or 0, 1),
        deadline=facts.deadline,
        evidence_ids=(f"benefit:{facts.benefit_id}",),
        citations=(Citation(
            clause_id=clause["clause_id"], citation=clause["citation"],
            clause_text=clause["clause_text"],
        ),),
    )]


def main() -> None:
    root = data_root()
    corpus_path = root / "prepared" / "benefits" / "current.json"
    if not corpus_path.exists():
        raise SystemExit("no prepared benefit corpus; run scripts/prepare_data.py first")
    corpus = _read_json(corpus_path)
    clauses = corpus.get("clauses", [])
    terms_version = str(corpus.get("terms_version") or "unavailable")
    sources = corpus.get("sources", {})
    guide_hashes = {
        source_id: row.get("content_sha256")
        for source_id, row in sorted(sources.items())
    }

    directory = registry_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    reviewed_path = directory / REVIEWED_FILENAME
    prior_path = directory / PRIOR_FILENAME

    # Build and write the reviewed local mapping, backing up the previous
    # reviewed file once (the prior file is local-only). Owner-directed
    # availability/account-state assumptions are embedded and reported.
    mapping_doc = build_assumption_mapping(clauses, terms_version)
    if reviewed_path.exists():
        prior_doc = _read_json(reviewed_path)
        if prior_doc.get("status") != ASSUMPTION_STATUS:
            prior_path.write_text(
                json.dumps(prior_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    reviewed_path.write_text(
        json.dumps(mapping_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    mapping = load_benefit_mapping(root, require_reviewed=True)

    # Re-run preparation so _prepare_rules sees the new fingerprint and re-ingests
    # every clause against the local real-data mapping.
    prepare_report = prepare_data(root=root)
    rule_result = prepare_report.get("rules", {})

    # Load the freshly ingested registry and the official-clause index metadata.
    registry_path = root / "prepared" / "rules" / "registry.sqlite3"
    registry = SQLiteRuleRegistry(path=registry_path)
    active_benefits = registry.active_benefits()
    active_benefit_ids = sorted({benefit.benefit_id for benefit in active_benefits})
    active_benefits_by_card = {}
    for benefit in active_benefits:
        active_benefits_by_card.setdefault(benefit.card, set()).add(benefit.benefit_id)
    active_benefits_by_card = {
        card: sorted(benefit_ids) for card, benefit_ids in sorted(active_benefits_by_card.items())
    }
    decisions = registry.decisions()
    index_metadata = _read_json(root / "prepared" / "indexes" / "official" / "metadata.json")["clauses"]

    # Retrieve only prepared, reviewed community ideas. These real public inputs
    # remain non-authoritative and cannot alter deterministic benefit facts.
    community_paths = sorted((root / "prepared" / "community").glob("*/current.json"))
    community_ideas = load_served_ideas(community_paths)
    community_retrieval = serve_community(
        community_ideas,
        benefit_ids=[row["benefit_id"] for row in mapping.rows],
        terms_version=terms_version,
    )

    # Evaluate real transaction evidence using recorded owner-directed
    # account-state assumptions plus this integration-only fallback: unresolved
    # descriptors are assumed outside the active benefit groups. The conservative
    # resolver default is unchanged; this can cause false-unused results.
    ledger = SQLiteLedger(root)
    merchant_decisions = ledger.decisions()
    merchant_resolution_counts = {
        "total": len(merchant_decisions),
        "resolved": sum(row.resolution_status == "resolved" for row in merchant_decisions),
        "indeterminate": sum(row.resolution_status == "indeterminate" for row in merchant_decisions),
    }
    with sqlite3.connect(ledger.path) as connection:
        fallback_descriptors = frozenset(
            row[0] for row in connection.execute(
                "SELECT descriptor FROM merchant_decisions WHERE resolution_status = 'indeterminate'"
            )
        )
    merchant_fallback = {
        "applied": True,
        "descriptor_count": len(fallback_descriptors),
        "assumption": "unresolved merchant descriptors are outside the 13 active benefit groups",
        "risk": "may cause false-unused results",
    }
    enrolled = {
        row["benefit_id"]: True
        for row in mapping.rows
        if row.get("disposition") == "supported" and row.get("enrollment_required")
    }
    portal_confirmed: dict[str, bool] = {}

    merchant_groups = {
        row["merchant_group"]: {row["merchant_group"]}
        for row in mapping.rows
        if row.get("disposition") == "supported" and row.get("merchant_group")
    }

    def evaluate(as_of):
        return dedupe(evaluate_persisted_benefits(
            registry_path, ledger, as_of, enrolled=enrolled, portal_confirmed=portal_confirmed,
            merchant_groups=merchant_groups,
            excluded_descriptors=fallback_descriptors,
        ))

    retrieve_official = build_offline_retriever(mapping, index_metadata, terms_version)
    runtime = ReActRuntime(
        question=QUESTION, as_of=AS_OF, evaluate=evaluate,
        retrieve_official=retrieve_official,
    )
    answer = runtime.run(ScriptedModel())

    # Multi-benefit planner over the same locally evaluated facts. Indeterminate facts
    # carry no verified remaining value/deadline, so the hard check drops them.
    facts = []
    for result in evaluate(AS_OF):
        if result.status in {"unused", "partially_used", "fully_used"}:
            remaining, deadline = result.remaining_minor, result.deadline
        else:
            remaining, deadline = None, None
        facts.append(BenefitFacts(
            benefit_id=_benefit_id(result), status=result.status,
            remaining_minor=remaining, deadline=deadline,
            evidence_ids=(f"benefit:{_benefit_id(result)}",),
        ))
    plan = plan_benefits(
        facts, clauses_by_benefit(mapping, index_metadata), researcher, as_of=AS_OF,
    )

    status_rows = [_status_dict(result) for result in evaluate(AS_OF)]
    status_counts = {
        status: sum(row["status"] == status for row in status_rows)
        for status in sorted({row["status"] for row in status_rows})
    }
    for row in status_rows:
        row["disposition"] = "supported"
    unresolved = [
        dict(row) for row in status_rows
        if row["status"] not in {"unused", "partially_used", "fully_used"}
    ] + [
        {"benefit_id": row["benefit_id"], "disposition": "known_untrackable",
         "status": "known_untrackable", "reason_codes": [], "used_minor": 0,
         "remaining_minor": None, "deadline": None, "evidence": _compact_evidence([])}
        for row in mapping.rows if row.get("disposition") == "known_untrackable"
    ] + [
        {"benefit_id": row["benefit_id"], "disposition": "indeterminate",
         "status": "indeterminate", "reason_codes": [], "used_minor": 0,
         "remaining_minor": None, "deadline": None, "evidence": _compact_evidence([])}
        for row in mapping.rows if row.get("disposition") == "indeterminate"
    ]

    output_dir = root / "prepared" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)

    assumptions_doc = mapping_doc["assumptions"]
    assumptions_path = output_dir / "vku-27-account-state-assumptions.json"
    assumptions_path.write_text(json.dumps(assumptions_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "dataset": "local-real-data-integration-vku-27",
        "dataset_version": "local-vku27-real-data-" + _sha256_text(
            json.dumps({"terms_version": terms_version, "mapping_fingerprint": mapping.fingerprint},
                       sort_keys=True)
        )[:16],
        "synthetic": False,
        "terms_version": terms_version,
        "as_of": AS_OF.isoformat(),
        "guide_hashes": guide_hashes,
        "mapping_fingerprint": mapping.fingerprint,
        "account_state_assumptions_fingerprint": _sha256_text(json.dumps(assumptions_doc, sort_keys=True)),
        "coverage": {
            "clause_count": len(clauses),
            "mapping_row_count": len(mapping.rows),
            "tallies": mapping_doc["tallies"],
            "active_rule_count": len(active_benefits),
            "distinct_active_benefit_count": len(active_benefit_ids),
            "active_benefit_ids": active_benefit_ids,
            "active_benefits_by_card": active_benefits_by_card,
            "structured_clause_count_by_card": {
                card: sum(1 for clause in clauses if clause["source_id"].startswith(card + ":"))
                for card in sorted({clause["source_id"].split(":", 1)[0] for clause in clauses})
            },
            "registry_decision_count": len(decisions),
            "merchant_decisions": merchant_resolution_counts,
            "merchant_fallback": merchant_fallback,
        },
        "outputs": {
            "assumptions": assumptions_path.relative_to(root).as_posix(),
        },
    }

    answer_dict = answer.model_dump(mode="json")
    answer_dict["evidence"] = [
        {"benefit_id": item.get("benefit_id"),
         "evidence": _compact_evidence(item.get("evidence_ids", []))}
        for item in answer_dict.get("evidence", [])
    ]

    report = {
        "dataset": manifest,
        "assumptions": assumptions_doc,
        "mapping": {
            "path": reviewed_path.relative_to(root).as_posix(),
            "prior_backup": prior_path.relative_to(root).as_posix() if prior_path.exists() else None,
            "fingerprint": mapping.fingerprint,
            "tallies": mapping_doc["tallies"],
        },
        "preparation": {
            "rules_ingestion": rule_result,
        },
        "evaluation": {
            "as_of": AS_OF.isoformat(),
            "status_counts": status_counts,
            "real_inputs": ["official_guides", "transactions", "public_community"],
            "question": QUESTION,
            "per_benefit": status_rows,
            "answer": answer_dict,
        },
        "merchant_resolution": merchant_resolution_counts,
        "merchant_fallback": merchant_fallback,
        "active_benefits_by_card": active_benefits_by_card,
        "community_retrieval": {
            "available": community_retrieval["available"],
            "idea_count": len(community_retrieval["ideas"]),
            "labels": community_retrieval["labels"],
        },
        "planner": {
            "fact_count": len(facts),
            "planned_count": len(plan.actions),
            "dropped_count": len(plan.dropped),
            "planned_actions": plan.model_dump(mode="json")["actions"],
            "dropped_actions": plan.model_dump(mode="json")["dropped"],
        },
        "unresolved_benefits": unresolved,
        "metrics": {
            "accuracy": None,
            "false_unused": None,
            "precision": None,
            "recall": None,
        },
        "observed_failures": [],
        "known_coverage_gaps": [
            "This integrates real staged guides, real local transaction evidence, and real public "
            "community inputs; community evidence is non-authoritative and cannot change status, "
            "amount, remaining value, or deadline.",
            f"Real transaction evidence has {merchant_resolution_counts['resolved']} resolved and "
            f"{merchant_resolution_counts['indeterminate']} indeterminate merchant decisions. "
            "This integration applies the explicit outside-group fallback to the indeterminate "
            "descriptors and records the false-unused risk.",
            "The prepared community corpus is real and non-authoritative; its short benefit IDs do "
            "not match the mapped IDs, so no community idea is attached to a mapped benefit.",
            "Chase guide benefits are individually structured from local text; unmapped "
            "benefits remain indeterminate rather than being invented.",
            "Non-dollar Amex benefits are known-untrackable and produce no active rules.",
            "Availability/current-selection and enrollment/portal account state are owner-directed "
            "assumptions, not issuer-portal observations.",
            "No human-labelled local cases exist, so accuracy/false-unused/precision/recall are unavailable (null).",
        ],
    }

    report_path = output_dir / "vku-27-local-real-data-integration-report.json"
    manifest_path = output_dir / "vku-27-local-real-data-integration-manifest.json"
    manifest["outputs"]["report"] = report_path.relative_to(root).as_posix()
    manifest["outputs"]["manifest"] = manifest_path.relative_to(root).as_posix()
    report["dataset"] = manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "mapping_path": reviewed_path.relative_to(root).as_posix(),
        "mapping_fingerprint": mapping.fingerprint,
        "tallies": mapping_doc["tallies"],
        "rules_ingestion": rule_result,
        "active_rule_count": len(active_benefits),
        "distinct_active_benefit_count": len(active_benefit_ids),
        "status_counts": {s: sum(1 for r in status_rows if r["status"] == s) for s in sorted({r["status"] for r in status_rows})},
        "planner": {
            "planned": len(plan.actions),
            "dropped": len(plan.dropped),
        },
        "report": report_path.relative_to(root).as_posix(),
        "manifest": manifest_path.relative_to(root).as_posix(),
        "assumptions": assumptions_path.relative_to(root).as_posix(),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
