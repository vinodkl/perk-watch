"""Deterministic benefit periods, matching, and four-valued status resolution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Iterable, Mapping

from .transactions import ResolvedTransaction, Transaction


@dataclass(frozen=True)
class Benefit:
    benefit_id: str
    card: str
    period_type: str
    period_amount_minor: int | None
    enrollment_required: bool = False
    portal_gated: bool = False
    merchant_group: str | None = None
    missing_data_source: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "Benefit":
        return cls(
            benefit_id=str(value["benefit_id"]), card=str(value["card"]),
            period_type=str(value["period_type"]),
            period_amount_minor=value["period_amount_minor"] if value["period_amount_minor"] is None else int(value["period_amount_minor"]),
            enrollment_required=bool(value.get("enrollment_required", False)),
            portal_gated=bool(value.get("portal_gated", False)),
            merchant_group=value.get("merchant_group"),
            missing_data_source=value.get("missing_data_source"),
        )


@dataclass(frozen=True)
class Period:
    start: date
    end: date


@dataclass(frozen=True)
class StatusResult:
    status: str
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    used_minor: int
    remaining_minor: int | None
    deadline: date | None = None


def load_benefit_registry(
    benefits_path: str | Path, *, merchant_groups_path: str | Path | None = None,
) -> tuple[list[Benefit], dict[str, set[str]], frozenset[str]]:
    """Load trackable benefits and the data-driven merchant-group table."""
    document = json.loads(Path(benefits_path).read_text(encoding="utf-8"))
    benefits = [Benefit.from_dict(row) for row in document["benefits"]]
    groups: dict[str, set[str]] = {}
    exclusions: frozenset[str] = frozenset()
    if merchant_groups_path is not None:
        group_document = json.loads(Path(merchant_groups_path).read_text(encoding="utf-8"))
        groups = {name: set(codes) for name, codes in group_document["groups"].items()}
        exclusions = frozenset(group_document.get("excluded_descriptors", []))
    return benefits, groups, exclusions


def benefit_period(period_type: str, as_of: date, *, cardmember_since: date | None = None) -> Period:
    """Return the calendar or anniversary benefit window containing ``as_of``."""
    if period_type == "monthly":
        start = as_of.replace(day=1)
        return Period(start, _next_month(start) - timedelta(days=1))
    if period_type == "quarterly":
        start = date(as_of.year, ((as_of.month - 1) // 3) * 3 + 1, 1)
        return Period(start, _add_months(start, 3) - timedelta(days=1))
    if period_type == "semiannual":
        start = date(as_of.year, 1 if as_of.month <= 6 else 7, 1)
        return Period(start, _add_months(start, 6) - timedelta(days=1))
    if period_type == "calendar_year":
        return Period(date(as_of.year, 1, 1), date(as_of.year, 12, 31))
    if period_type == "four_year":
        start = date(as_of.year - as_of.year % 4, 1, 1)
        return Period(start, date(start.year + 3, 12, 31))
    if period_type == "cardmember_year":
        if cardmember_since is None:
            raise ValueError("cardmember_year requires cardmember_since")
        anniversary = _anniversary(cardmember_since, as_of.year)
        if as_of < anniversary:
            anniversary = _anniversary(cardmember_since, as_of.year - 1)
        return Period(anniversary, _anniversary(cardmember_since, anniversary.year + 1) - timedelta(days=1))
    raise ValueError(f"unsupported period type: {period_type}")


def evaluate_all_benefits(
    benefits: Iterable[Benefit], ledger: object, as_of: date, *,
    cardmember_since: Mapping[str, date] | None = None,
    enrolled: Mapping[str, bool | None] | None = None,
    portal_confirmed: Mapping[str, bool | None] | None = None,
    limit_minor: Mapping[str, int | None] | None = None,
    observed_on: Mapping[str, date] | None = None,
    merchant_groups: Mapping[str, set[str]] | None = None,
    excluded_descriptors: frozenset[str] | set[str] | None = None,
) -> list[StatusResult]:
    """Evaluate persisted facts only; this path deliberately accepts no resolver."""
    transactions = ledger.load_resolved_transactions() if hasattr(ledger, "load_resolved_transactions") else ledger
    return resolve_benefits(
        benefits, transactions, as_of, cardmember_since=cardmember_since, enrolled=enrolled,
        portal_confirmed=portal_confirmed, limit_minor=limit_minor, observed_on=observed_on,
        merchant_groups=merchant_groups, excluded_descriptors=excluded_descriptors,
    )


def resolve_benefits(
    benefits: Iterable[Benefit], transactions: Iterable[Transaction | ResolvedTransaction], as_of: date, *,
    cardmember_since: Mapping[str, date] | None = None,
    enrolled: Mapping[str, bool | None] | None = None,
    portal_confirmed: Mapping[str, bool | None] | None = None,
    limit_minor: Mapping[str, int | None] | None = None,
    observed_on: Mapping[str, date] | None = None,
    merchant_groups: Mapping[str, set[str]] | None = None,
    excluded_descriptors: frozenset[str] | set[str] | None = None,
) -> list[StatusResult]:
    """Evaluate every registered benefit at one as-of date, without model involvement."""
    rows = tuple(transactions)
    return [resolve_status(
        benefit, rows, as_of,
        cardmember_since=(cardmember_since or {}).get(benefit.card),
        enrolled=(enrolled or {}).get(benefit.benefit_id),
        portal_confirmed=(portal_confirmed or {}).get(benefit.benefit_id),
        limit_minor=(limit_minor or {}).get(benefit.benefit_id), observed_on=observed_on,
        merchant_groups=merchant_groups, excluded_descriptors=excluded_descriptors,
    ) for benefit in benefits]


def resolve_status(
    benefit: Benefit,
    transactions: Iterable[Transaction | ResolvedTransaction],
    as_of: date,
    *,
    cardmember_since: date | None = None,
    limit_minor: int | None = None,
    enrolled: bool | None = None,
    portal_confirmed: bool | None = None,
    observed_on: Mapping[str, date] | None = None,
    period_as_of: date | None = None,
    merchant_groups: Mapping[str, set[str]] | None = None,
    excluded_descriptors: frozenset[str] | set[str] | None = None,
) -> StatusResult:
    """Resolve status from supplied facts only. No model participates in this calculation."""
    if benefit.missing_data_source and not benefit.merchant_group:
        return StatusResult("deferred", ("non_observable_benefit",),
                            (f"benefit:{benefit.benefit_id}", f"missing_source:{benefit.missing_data_source}"), 0, None, None)
    if benefit.period_type == "cardmember_year" and cardmember_since is None:
        return StatusResult("indeterminate", ("missing_cardmember_anniversary",), (f"benefit:{benefit.benefit_id}",), 0, None, as_of)
    period = benefit_period(benefit.period_type, period_as_of or as_of, cardmember_since=cardmember_since)
    limit = benefit.period_amount_minor if limit_minor is None else limit_minor
    evidence = [f"benefit:{benefit.benefit_id}", f"period:{period.start.isoformat()}:{period.end.isoformat()}"]
    if limit is None:
        return StatusResult("indeterminate", ("unknown_period_limit",), tuple(evidence), 0, None, period.end)
    if benefit.enrollment_required:
        if enrolled is not None:
            evidence.append(f"enrollment:{benefit.benefit_id}")
        if enrolled is not True:
            reason = "enrollment_not_confirmed" if enrolled is False else "missing_enrollment_evidence"
            return StatusResult("indeterminate", (reason,), tuple(evidence), 0, limit, period.end)
    if benefit.portal_gated:
        if portal_confirmed is not None:
            evidence.append(f"portal:{benefit.benefit_id}")
        if portal_confirmed is not True:
            reason = "portal_not_confirmed" if portal_confirmed is False else "missing_portal_evidence"
            return StatusResult("indeterminate", (reason,), tuple(evidence), 0, limit, period.end)
    group = benefit.merchant_group
    if group is None:
        return StatusResult("indeterminate", ("missing_eligibility_policy",), tuple(evidence), 0, limit, period.end)
    eligible_merchants = (merchant_groups or {}).get(group, set())

    eligible: list[Transaction] = []
    uncertain: list[tuple[str, str]] = []
    for item in sorted(transactions, key=lambda value: _facts(value)[0].transaction_id):
        transaction, merchant = _facts(item)
        if transaction.card != benefit.card or not period.start <= transaction.transaction_date <= period.end:
            continue
        if transaction.transaction_date > as_of:
            uncertain.append(("transaction_not_yet_occurred", transaction.transaction_id))
            continue
        if observed_on and transaction.transaction_id in observed_on and observed_on[transaction.transaction_id] > as_of:
            uncertain.append(("posting_lag", transaction.transaction_id))
            continue
        if merchant in eligible_merchants:
            eligible.append(transaction)
        elif merchant is None and transaction.descriptor not in (excluded_descriptors or frozenset()):
            uncertain.append(("unresolved_merchant", transaction.transaction_id))
    evidence.extend(f"transaction:{row.transaction_id}" for row in eligible)
    evidence.extend(f"uncertain_transaction:{value}" for _, value in uncertain)
    if uncertain:
        return StatusResult("indeterminate", tuple(sorted({reason for reason, _ in uncertain})), tuple(evidence), 0, limit, period.end)

    used = min(limit, sum(max(0, row.amount_minor) for row in eligible))
    remaining = limit - used
    if used == limit:
        return StatusResult("fully_used", ("period_limit_reached",), tuple(evidence), used, remaining, period.end)
    if used:
        return StatusResult("partially_used", ("eligible_transaction_found",), tuple(evidence), used, remaining, period.end)
    return StatusResult("unused", ("no_eligible_transactions",), tuple(evidence), used, remaining, period.end)


def _facts(item: Transaction | ResolvedTransaction) -> tuple[Transaction, str | None]:
    if isinstance(item, ResolvedTransaction):
        return item.transaction, item.canonical_merchant
    return item, None


def _next_month(value: date) -> date:
    return _add_months(value, 1)


def _add_months(value: date, months: int) -> date:
    year, month = divmod(value.month - 1 + months, 12)
    return date(value.year + year, month + 1, 1)


def _anniversary(start: date, year: int) -> date:
    if start.month == 2 and start.day == 29 and not _leap(year):
        return date(year, 2, 28)
    return date(year, start.month, start.day)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
