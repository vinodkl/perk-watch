"""Period-by-period credit tracking from issuer statement-credit lines."""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta

from ..cards import load_cards
from ..catalog import CatalogBenefit, load_catalog, match_credit

# Days before a period ends when unused value counts as "at risk".
AT_RISK_DAYS = {"monthly": 7, "quarterly": 14, "semiannual": 30, "annual": 45}
# Issuer credits post a few days after the purchase, so a closed period stays "pending"
# until statements cover this many days past its end.
PENDING_GRACE_DAYS = 10
_STEP = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}

Marks = dict[tuple[str, str], int]


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    return date(value.year + month // 12, month % 12 + 1, 1)


def _label(period: str, start: date) -> str:
    if period == "monthly":
        return calendar.month_abbr[start.month]
    if period == "quarterly":
        return f"Q{(start.month - 1) // 3 + 1}"
    if period == "semiannual":
        return "H1" if start.month == 1 else "H2"
    return str(start.year)


def periods_for(benefit: CatalogBenefit, as_of: date) -> list[tuple[date, date, str]]:
    """Calendar periods of as_of's year, from January 1 through the period containing as_of."""
    out, start = [], date(as_of.year, 1, 1)
    while start <= as_of and start.year == as_of.year:
        end = _add_months(start, _STEP[benefit.period]) - timedelta(days=1)
        out.append((start, end, _label(benefit.period, start)))
        start = end + timedelta(days=1)
    return out


def _matched_credits(db: sqlite3.Connection, catalog: tuple[CatalogBenefit, ...]) -> tuple[dict[str, list[dict]], int]:
    matched: dict[str, list[dict]] = {b.benefit_id: [] for b in catalog}
    unmatched = 0
    for card_id, card in load_cards().items():
        sign = -1 if card["statement_credit_sign"] == "negative" else 1
        rows = db.execute("SELECT transaction_id, posted_date, description, amount_minor FROM transactions "
                          "WHERE card_id = ? AND lower(description) LIKE '%credit%' ORDER BY posted_date",
                          (card_id,)).fetchall()
        for transaction_id, posted, description, amount in rows:
            if amount * sign <= 0:
                continue  # a purchase or reversal, not an issuer credit
            try:
                benefit_id = match_credit(card_id, description, catalog)
            except ValueError:
                benefit_id = None
            if benefit_id:
                matched[benefit_id].append({"transaction_id": transaction_id, "date": posted, "amount_minor": abs(amount)})
            else:
                unmatched += 1
    return matched, unmatched


def data_through(db: sqlite3.Connection) -> dict[str, str | None]:
    return {card_id: db.execute("SELECT MAX(posted_date) FROM transactions WHERE card_id = ?", (card_id,)).fetchone()[0]
            for card_id in load_cards()}


def _status(benefit: CatalogBenefit, end: date, used: int, amount: int, as_of: date, covered: date | None) -> str:
    if used >= amount:
        return "used"
    if end >= as_of:
        return "at_risk" if (end - as_of).days + 1 <= AT_RISK_DAYS[benefit.period] else "open"
    if benefit.tracking == "manual" and used == 0:
        return "unmarked"  # in-app credits never reach the statement; only the user can confirm them
    if covered is None or end + timedelta(days=PENDING_GRACE_DAYS) > covered:
        return "pending"
    return "partial" if used else "missed"


def track(db: sqlite3.Connection, as_of: date, marks: Marks | None = None,
          catalog: tuple[CatalogBenefit, ...] | None = None) -> dict:
    """Every catalog credit with its period history, current status and yearly totals."""
    catalog = catalog or load_catalog()
    marks = marks or {}
    cards = load_cards()
    credits, unmatched = _matched_credits(db, catalog)
    through = data_through(db)
    terms = dict(db.execute("SELECT benefit_id, terms FROM benefits").fetchall())
    benefits = []
    for benefit in catalog:
        covered = date.fromisoformat(through[benefit.card_id]) if through.get(benefit.card_id) else None
        periods = []
        for start, end, label in periods_for(benefit, as_of):
            amount = benefit.amount_for(start.month) if benefit.period == "monthly" else benefit.amount_minor
            hits = [c for c in credits[benefit.benefit_id] if start.isoformat() <= c["date"] <= end.isoformat()]
            key = (benefit.benefit_id, start.isoformat())
            used = min(amount, sum(c["amount_minor"] for c in hits) + marks.get(key, 0))
            periods.append({"label": label, "start": start.isoformat(), "end": end.isoformat(),
                            "amount_minor": amount, "used_minor": used,
                            "status": _status(benefit, end, used, amount, as_of, covered),
                            "credits": hits, "marked": key in marks})
        current = dict(periods[-1])
        current["days_left"] = (date.fromisoformat(current["end"]) - as_of).days + 1
        current["remaining_minor"] = current["amount_minor"] - current["used_minor"]
        benefits.append({
            "benefit_id": benefit.benefit_id, "card_id": benefit.card_id,
            "card": cards[benefit.card_id]["display_name"], "title": benefit.title, "period": benefit.period,
            "tracking": benefit.tracking, "category": benefit.category,
            "enrollment_required": benefit.enrollment_required,
            "current": current, "periods": periods,
            "ytd": {"captured_minor": sum(p["used_minor"] for p in periods),
                    "missed_minor": sum(p["amount_minor"] - p["used_minor"] for p in periods
                                        if p["status"] in {"missed", "partial"})},
            "terms": terms.get(benefit.benefit_id, ""),
        })
    return {
        "as_of": as_of.isoformat(), "data_through": through,
        "totals": {"captured_minor": sum(b["ytd"]["captured_minor"] for b in benefits),
                   "missed_minor": sum(b["ytd"]["missed_minor"] for b in benefits),
                   "at_risk_minor": sum(b["current"]["remaining_minor"] for b in benefits
                                        if b["current"]["status"] == "at_risk")},
        "unmatched_credit_lines": unmatched,
        "benefits": benefits,
    }


def benefit_state(db: sqlite3.Connection, benefit_id: str, as_of: date, marks: Marks | None = None) -> dict | None:
    return next((b for b in track(db, as_of, marks)["benefits"] if b["benefit_id"] == benefit_id), None)
