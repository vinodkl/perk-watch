"""Offline Extractor/Verifier ingestion and the persisted computation registry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable, Mapping

from .benefits import Benefit


@dataclass(frozen=True)
class RuleProposal:
    benefit_id: str
    card: str | None
    period_type: str | None
    period_amount_minor: int | None
    eligibility: Mapping[str, Any]
    enrollment_required: bool
    portal_gated: bool


@dataclass(frozen=True)
class VerificationDecision:
    outcome: str
    reason: str


class SQLiteRuleRegistry:
    """Versioned active rules plus immutable ingestion decisions."""

    def __init__(self, root: str | Path | None = None, *, path: str | Path | None = None):
        if path is not None and root is not None:
            raise ValueError("pass root or path, not both")
        if path is None:
            from .raw_data import data_root
            path = (Path(root).expanduser() if root is not None else data_root()) / "prepared" / "rules" / "registry.sqlite3"
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS active_rules (
                    clause_id TEXT PRIMARY KEY, benefit_id TEXT NOT NULL, card TEXT,
                    source_id TEXT NOT NULL, terms_version TEXT NOT NULL,
                    effective_from TEXT, effective_to TEXT, period_type TEXT,
                    period_amount_minor INTEGER, eligibility_json TEXT NOT NULL,
                    enrollment_required INTEGER NOT NULL, portal_gated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rule_decisions (
                    clause_id TEXT NOT NULL, terms_version TEXT NOT NULL,
                    source_id TEXT NOT NULL, benefit_id TEXT NOT NULL,
                    outcome TEXT NOT NULL, reason TEXT NOT NULL,
                    proposal_json TEXT NOT NULL, clause_json TEXT NOT NULL,
                    PRIMARY KEY (clause_id, terms_version)
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            """)

    def ingest(
        self,
        clauses: Iterable[Mapping[str, Any]],
        *,
        extractor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        verifier: Callable[[Mapping[str, Any], Mapping[str, Any]], VerificationDecision | Mapping[str, Any] | str] | None = None,
        changed_clause_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Ingest clauses without exposing extractor output beyond the verifier."""
        extract = extractor or extract_rule
        check = verifier or verify_rule
        clauses = list(clauses)
        accepted = rejected = skipped = 0
        with self._connect() as db:
            for clause in clauses:
                clause_id = str(clause["clause_id"])
                terms_version = str(clause["terms_version"])
                if changed_clause_ids is not None and clause_id not in changed_clause_ids:
                    skipped += 1
                    continue
                prior = db.execute(
                    "SELECT 1 FROM rule_decisions WHERE clause_id=? AND terms_version=?",
                    (clause_id, terms_version),
                ).fetchone()
                if prior is not None:
                    skipped += 1
                    continue
                extracted = extract(clause)
                proposal = asdict(extracted) if isinstance(extracted, RuleProposal) else dict(extracted)
                decision = _decision(check(clause, proposal))
                db.execute("DELETE FROM active_rules WHERE clause_id=?", (clause_id,))
                db.execute(
                    "INSERT INTO rule_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (clause_id, terms_version, str(clause.get("source_id", clause.get("source_ref", ""))),
                     str(clause.get("benefit_id", "")), decision.outcome, decision.reason,
                     json.dumps(proposal, sort_keys=True), json.dumps(dict(clause), sort_keys=True)),
                )
                if decision.outcome == "supported":
                    db.execute(
                        "INSERT INTO active_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _rule_values(clause, proposal),
                    )
                    accepted += 1
                else:
                    rejected += 1
            # A benefit is active only when every current clause for it is supported.
            for clause in clauses:
                decision = db.execute(
                    "SELECT outcome FROM rule_decisions WHERE clause_id=? AND terms_version=?",
                    (clause["clause_id"], clause["terms_version"]),
                ).fetchone()
                if decision is not None and decision["outcome"] != "supported":
                    db.execute("DELETE FROM active_rules WHERE benefit_id=?", (clause.get("benefit_id"),))
        return {"accepted": accepted, "rejected": rejected, "skipped": skipped}

    def active_rule_provenance(self) -> list[dict[str, Any]]:
        """Return each active rule joined to its ``supported`` ingestion decision."""
        with self._connect() as db:
            rows = db.execute("""
                SELECT a.clause_id, a.benefit_id, a.card, a.source_id, a.terms_version,
                       a.effective_from, a.effective_to, a.period_type, a.period_amount_minor,
                       a.eligibility_json, a.enrollment_required, a.portal_gated,
                       d.outcome AS decision_outcome, d.reason AS decision_reason,
                       d.source_id AS decision_source_id, d.benefit_id AS decision_benefit_id,
                       d.proposal_json AS decision_proposal_json
                FROM active_rules a
                JOIN rule_decisions d ON d.clause_id = a.clause_id AND d.terms_version = a.terms_version
                WHERE d.outcome = 'supported'
                ORDER BY a.benefit_id, a.clause_id
            """).fetchall()
        return [dict(row) for row in rows]

    def applied_mapping_fingerprint(self) -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='mapping_fingerprint'").fetchone()
        return str(row["value"]) if row else ""

    def set_applied_mapping_fingerprint(self, value: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO meta (key, value) VALUES ('mapping_fingerprint', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (value,),
            )

    def clear_decisions_for(self, clause_ids: set[str]) -> None:
        """Delete decisions (and active rules) for clauses before re-deciding them."""
        with self._connect() as db:
            if clause_ids:
                marks = ",".join("?" for _ in clause_ids)
                db.execute(f"DELETE FROM rule_decisions WHERE clause_id IN ({marks})", tuple(clause_ids))
                db.execute(f"DELETE FROM active_rules WHERE clause_id IN ({marks})", tuple(clause_ids))
            else:
                db.execute("DELETE FROM rule_decisions")
                db.execute("DELETE FROM active_rules")

    def remove_missing(self, clause_ids: set[str]) -> None:
        with self._connect() as db:
            if clause_ids:
                marks = ",".join("?" for _ in clause_ids)
                db.execute(f"DELETE FROM active_rules WHERE clause_id NOT IN ({marks})", tuple(clause_ids))
            else:
                db.execute("DELETE FROM active_rules")

    def active_benefits(self) -> list[Benefit]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM active_rules ORDER BY benefit_id, clause_id").fetchall()
        return [_benefit(row) for row in rows]

    def decisions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM rule_decisions ORDER BY clause_id, terms_version")]


def extract_rule(clause: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the Extractor's structured output."""
    text = str(clause.get("text", ""))
    period = clause.get("period_type") or _period(text)
    amount = clause.get("period_amount_minor")
    if amount is None:
        match = re.search(r"\$(\d+(?:\.\d{1,2})?)", text)
        amount = round(float(match.group(1)) * 100) if match else None
    eligibility = clause.get("eligibility")
    if eligibility is None:
        eligibility = {"source_text": text}
        if clause.get("merchant_group"):
            eligibility["merchant_group"] = clause["merchant_group"]
    return {
        "benefit_id": clause.get("benefit_id"), "card": clause.get("card") or _card(clause.get("benefit_id")),
        "period_type": period, "period_amount_minor": amount, "eligibility": eligibility,
        "enrollment_required": bool(clause.get("enrollment_required", "enroll" in text.lower())),
        "portal_gated": bool(clause.get("portal_gated", "portal" in text.lower())),
    }


def verify_rule(clause: Mapping[str, Any], proposal: Mapping[str, Any]) -> VerificationDecision:
    """Verify only clause and proposal, never extractor reasoning or hidden context."""
    if not str(proposal.get("benefit_id") or "").strip():
        return VerificationDecision("partial_support", "clause is not mapped to a benefit")
    required = ("benefit_id", "period_type", "period_amount_minor", "eligibility")
    if any(key not in proposal for key in required) or not proposal.get("benefit_id") or not proposal.get("period_type"):
        return VerificationDecision("partial_support", "proposal is missing structured rule fields")
    for key in ("benefit_id", "period_type", "period_amount_minor"):
        if key in clause and clause[key] is not None and proposal.get(key) != clause[key]:
            return VerificationDecision("disagreement", f"proposal disagrees on {key}")
    eligibility = proposal["eligibility"]
    if not isinstance(eligibility, Mapping):
        return VerificationDecision("partial_support", "eligibility is not structured")
    if not str(eligibility.get("merchant_group") or "").strip():
        return VerificationDecision("partial_support", "eligibility is missing a merchant group")
    return VerificationDecision("supported", "clause supports the complete proposal")


def load_rule_registry(path: str | Path) -> SQLiteRuleRegistry:
    return SQLiteRuleRegistry(path=path)


def _rule_values(clause: Mapping[str, Any], proposal: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        clause["clause_id"], proposal["benefit_id"], proposal.get("card"),
        clause.get("source_id", clause.get("source_ref", "")), clause["terms_version"],
        clause.get("effective_from"), clause.get("effective_to"), proposal.get("period_type"),
        proposal.get("period_amount_minor"), json.dumps(proposal.get("eligibility", {}), sort_keys=True),
        int(bool(proposal.get("enrollment_required"))), int(bool(proposal.get("portal_gated"))),
    )


def _benefit(row: sqlite3.Row) -> Benefit:
    if not str(row["benefit_id"] or "").strip():
        raise ValueError("active_rules contains an unmapped row; refusing to load it")
    return Benefit(
        benefit_id=row["benefit_id"], card=row["card"] or _card(row["benefit_id"]),
        period_type=row["period_type"], period_amount_minor=row["period_amount_minor"],
        enrollment_required=bool(row["enrollment_required"]), portal_gated=bool(row["portal_gated"]),
        merchant_group=json.loads(row["eligibility_json"]).get("merchant_group"),
    )


def _decision(value: VerificationDecision | Mapping[str, Any] | str) -> VerificationDecision:
    if isinstance(value, VerificationDecision):
        return value
    if isinstance(value, str):
        return VerificationDecision(value, value)
    return VerificationDecision(str(value.get("outcome", value.get("status", "partial_support"))), str(value.get("reason", "")))


def _period(text: str) -> str | None:
    lower = text.lower()
    for value, words in (("monthly", ("month",)), ("quarterly", ("quarter",)), ("semiannual", ("half", "semiannual")), ("calendar_year", ("calendar year", "year")), ("four_year", ("four-year", "four year")), ("cardmember_year", ("cardmember year",))):
        if any(word in lower for word in words):
            return value
    return None


def _card(benefit_id: object) -> str | None:
    value = str(benefit_id or "")
    for prefix in ("amex_platinum", "chase_sapphire_preferred"):
        if value.startswith(prefix):
            return prefix
    return None
