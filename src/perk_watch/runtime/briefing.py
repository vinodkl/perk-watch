"""Group calculated benefits for the read-only app briefing."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

from .calculations import calculate_all


def build_briefing(db: sqlite3.Connection, *, as_of: date | str | None = None,
                   account_year_start: date | str | None = None,
                   window_days: int = 14) -> dict[str, object]:
    current = as_of if isinstance(as_of, date) else date.fromisoformat(as_of) if as_of else date.today()
    groups: dict[str, list[dict[str, object]]] = {
        "act_soon": [], "check_yourself": [], "on_track": []}
    reasons: dict[str, list[str]] = defaultdict(list)

    for calculation in calculate_all(
            db, as_of=current, account_year_start=account_year_start):
        item = dict(calculation)
        item["partially_used"] = (
            item["status"] == "available" and int(item["used_amount_minor"] or 0) > 0)
        if item["status"] == "unknown":
            item["action"] = _action(str(item["reason"]))
            groups["check_yourself"].append(item)
            reasons[str(item["reason"])].append(str(item["benefit_id"]))
        elif (item["status"] == "available"
              and int(item["remaining_amount_minor"] or 0) > 0
              and (date.fromisoformat(str(item["deadline"])) - current).days <= window_days):
            groups["act_soon"].append(item)
        else:
            groups["on_track"].append(item)

    reason_groups = [
        {"reason": reason, "count": len(benefit_ids), "benefit_ids": benefit_ids,
         "action": _action(reason)}
        for reason, benefit_ids in sorted(reasons.items())
    ]
    return {
        "as_of": current.isoformat(),
        "window_days": window_days,
        "groups": groups,
        "unknown_reason_groups": reason_groups,
        "statements": statement_ranges(db, current),
    }


def statement_ranges(db: sqlite3.Connection, as_of: date | str | None = None) -> list[dict[str, object]]:
    current = as_of if isinstance(as_of, date) else date.fromisoformat(as_of) if as_of else date.today()
    rows = db.execute(
        "SELECT c.card_id, c.display_name, MIN(t.posted_date), MAX(t.posted_date) "
        "FROM cards c LEFT JOIN transactions t ON t.card_id = c.card_id "
        "GROUP BY c.card_id, c.display_name ORDER BY c.display_name"
    ).fetchall()
    return [
        {"card_id": card_id, "display_name": display_name,
         "first_posted_date": first_posted, "last_posted_date": last_posted,
         "stale": last_posted is None or current > date.fromisoformat(last_posted)}
        for card_id, display_name, first_posted, last_posted in rows
    ]


def _action(reason: str) -> str:
    if "account-year" in reason:
        return "Add the account anniversary before relying on this amount."
    if "merchant" in reason:
        return "Review unmatched transactions before relying on this amount."
    if "amount" in reason or "period" in reason:
        return "Check the current official terms."
    return "Review this benefit and its source data."
