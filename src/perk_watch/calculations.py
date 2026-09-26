"""Exact benefit-period calculations over prepared SQLite transactions."""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta


def _date(value: date | str | None) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value) if value else date.today()


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _period_bounds(period: str | None, as_of: date, account_year_start: date | str | None) -> tuple[date, date] | None:
    kind = (period or "").strip().lower().replace("-", "_").replace(" ", "_")
    if kind in {"monthly", "month"}:
        start = as_of.replace(day=1)
        return start, _add_months(start, 1) - timedelta(days=1)
    if kind in {"quarterly", "quarter"}:
        start = date(as_of.year, ((as_of.month - 1) // 3) * 3 + 1, 1)
        return start, _add_months(start, 3) - timedelta(days=1)
    if kind in {"yearly", "annual", "calendar_year", "year"}:
        start = date(as_of.year, 1, 1)
        return start, date(as_of.year, 12, 31)
    if kind in {"account_year", "account_yearly", "cardmember_year"} and account_year_start:
        anniversary = _date(account_year_start)
        start = date(as_of.year, anniversary.month, anniversary.day)
        if start > as_of:
            start = date(as_of.year - 1, anniversary.month, anniversary.day)
        return start, _add_months(start, 12) - timedelta(days=1)
    return None


def _merchants(value: str | None) -> set[str]:
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def calculate_benefit(db: sqlite3.Connection, benefit_id: str, *, as_of: date | str | None = None,
                      account_year_start: date | str | None = None) -> dict[str, object]:
    row = db.execute(
        "SELECT benefit_id, card_id, title, amount_minor, period, eligible_merchants "
        "FROM benefits WHERE benefit_id = ?", (benefit_id,)).fetchone()
    if not row:
        return _unknown(benefit_id, "benefit was not found")
    current = _date(as_of)
    bounds = _period_bounds(row[4], current, account_year_start)
    if row[3] is None:
        return _unknown_row(row, "benefit amount is unknown")
    if bounds is None:
        return _unknown_row(row, "benefit period or account-year boundary is unknown")
    merchants = _merchants(row[5])
    if not merchants:
        return _unknown_row(row, "eligible merchants are unknown")
    start, end = bounds
    transactions = db.execute(
        "SELECT t.transaction_id, t.posted_date, t.amount_minor, t.merchant, "
        "cm.benefit_id FROM transactions t LEFT JOIN credit_matches cm "
        "ON cm.transaction_id = t.transaction_id WHERE t.card_id = ? "
        "AND t.posted_date BETWEEN ? AND ? ORDER BY t.posted_date, t.transaction_id",
        (row[1], start.isoformat(), end.isoformat())).fetchall()
    supporting, total, uncertain = [], 0, 0
    for transaction_id, posted_date, amount, merchant, matched_benefit in transactions:
        if matched_benefit == benefit_id:
            contribution = abs(amount)
        elif merchant and merchant.lower() in merchants:
            contribution = amount
        elif merchant is None:
            uncertain += 1
            continue
        else:
            continue
        supporting.append(transaction_id)
        total += contribution
    used = max(0, min(int(row[3]), total))
    result = {"benefit_id": row[0], "card_id": row[1], "title": row[2], "status": "available",
              "used_amount_minor": used, "remaining_amount_minor": int(row[3]) - used,
              "deadline": end.isoformat(), "supporting_transaction_ids": supporting,
              "reason": "calculated from eligible transactions"}
    if uncertain:
        result["status"] = "unknown"
        result["used_amount_minor"] = None
        result["remaining_amount_minor"] = None
        result["reason"] = f"merchant eligibility is unknown for {uncertain} transaction(s)"
    elif used >= int(row[3]):
        result["status"] = "exhausted"
        result["reason"] = "benefit amount has been used"
    return result


def _unknown(benefit_id: str, reason: str) -> dict[str, object]:
    return {"benefit_id": benefit_id, "status": "unknown", "used_amount_minor": None,
            "remaining_amount_minor": None, "deadline": None,
            "supporting_transaction_ids": [], "reason": reason}


def _unknown_row(row: tuple[object, ...], reason: str) -> dict[str, object]:
    result = _unknown(str(row[0]), reason)
    result.update({"card_id": row[1], "title": row[2]})
    return result


def calculate_all(db: sqlite3.Connection, *, as_of: date | str | None = None,
                  account_year_start: date | str | None = None) -> list[dict[str, object]]:
    ids = [row[0] for row in db.execute("SELECT benefit_id FROM benefits ORDER BY card_id, title, benefit_id")]
    return [calculate_benefit(db, benefit_id, as_of=as_of, account_year_start=account_year_start) for benefit_id in ids]
