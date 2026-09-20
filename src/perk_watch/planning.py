"""Small multi-benefit planning flow: isolated fan-out, synthesis, hard checks.

Each researcher receives one benefit's verified facts and official clauses only.
Fan-out is multi-agent because each bounded researcher has an isolated context;
synthesis is a plain deterministic pass, so no supervisor or graph runtime is needed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .react import Citation


class BenefitFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benefit_id: str
    status: str
    remaining_minor: int | None
    deadline: date | None
    evidence_ids: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)


class CandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benefit_id: str
    action: str
    value_minor: int
    spend_minor: int | None = None
    qualifying_merchants: tuple[str, ...] = ()
    booking_channel: str | None = None
    enrollment_lead_time_days: int = 0
    minimum_spend_minor: int | None = None
    deadline: date | None = None
    conflicts: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


class ResearchResult(BaseModel):
    benefit_id: str
    candidates: list[CandidateAction] = Field(default_factory=list)
    community: dict[str, Any] = Field(default_factory=lambda: {
        "available": False, "reason": "community retrieval unavailable", "ideas": []
    })


class PlannedAction(CandidateAction):
    pass


class DroppedAction(BaseModel):
    action: CandidateAction
    reason: str


class PlanResult(BaseModel):
    actions: list[PlannedAction]
    dropped: list[DroppedAction]
    researchers: list[ResearchResult]
    community: dict[str, Any]


class BenefitResearcher(Protocol):
    def __call__(self, facts: BenefitFacts, clauses: list[Mapping[str, Any]]) -> list[CandidateAction]: ...


def plan_benefits(
    facts: list[BenefitFacts],
    clauses_by_benefit: Mapping[str, list[Mapping[str, Any]]],
    researcher: BenefitResearcher,
    *,
    as_of: date,
    max_workers: int | None = None,
) -> PlanResult:
    """Research each benefit in isolation, then order and hard-filter actions."""
    def run(item: BenefitFacts) -> ResearchResult:
        clauses = list(clauses_by_benefit.get(item.benefit_id, []))
        allowed = {str(row.get("clause_id")) for row in clauses}
        candidates = []
        for candidate in researcher(item, clauses)[:3]:
            if candidate.benefit_id != item.benefit_id:
                continue
            if not clauses or not candidate.citations or any(c.clause_id not in allowed for c in candidate.citations):
                continue
            candidates.append(candidate.model_copy(update={
                "evidence_ids": tuple(dict.fromkeys(item.evidence_ids + candidate.evidence_ids)),
                "deadline": candidate.deadline or item.deadline,
            }))
        return ResearchResult(benefit_id=item.benefit_id, candidates=candidates)

    with ThreadPoolExecutor(max_workers=max_workers or min(8, max(1, len(facts)))) as pool:
        researched = list(pool.map(run, facts))
    by_id = {item.benefit_id: item for item in facts}
    candidates = [candidate for result in researched for candidate in result.candidates]
    candidates.sort(key=lambda item: (item.deadline or date.max, item.benefit_id, item.action))

    accepted: list[PlannedAction] = []
    dropped: list[DroppedAction] = []
    for candidate in candidates:
        fact = by_id[candidate.benefit_id]
        reason = _reject_reason(candidate, fact, accepted, as_of)
        if reason:
            dropped.append(DroppedAction(action=candidate, reason=reason))
        else:
            accepted.append(PlannedAction.model_validate(candidate.model_dump()))
    return PlanResult(
        actions=accepted, dropped=dropped, researchers=researched,
        community={"available": False, "reason": "community retrieval unavailable", "ideas": []},
    )


def _reject_reason(candidate: CandidateAction, fact: BenefitFacts, accepted: list[PlannedAction], as_of: date) -> str | None:
    if fact.remaining_minor is None or candidate.value_minor > fact.remaining_minor:
        return "exceeds_remaining_value"
    if fact.deadline is None or candidate.deadline is None:
        return "missing_deadline"
    if candidate.deadline > fact.deadline:
        return "violates_deadline"
    if as_of + timedelta(days=candidate.enrollment_lead_time_days) > candidate.deadline:
        return "cannot_complete_before_deadline"
    if candidate.minimum_spend_minor is not None and candidate.spend_minor is not None and candidate.spend_minor < candidate.minimum_spend_minor:
        return "violates_minimum_spend"
    constraints = fact.constraints
    if constraints.get("qualifying_merchants") and not set(candidate.qualifying_merchants) <= set(constraints["qualifying_merchants"]):
        return "violates_merchant_constraint"
    if constraints.get("booking_channel") and candidate.booking_channel != constraints["booking_channel"]:
        return "violates_booking_channel"
    if constraints.get("enrollment_lead_time_days", 0) > candidate.enrollment_lead_time_days:
        return "violates_enrollment_lead_time"
    accepted_ids = {item.benefit_id for item in accepted}
    if set(candidate.conflicts) & accepted_ids:
        return "conflicts_with_ordered_plan"
    return None
