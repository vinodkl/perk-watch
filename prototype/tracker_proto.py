"""PROTOTYPE (throwaway): period-by-period benefit tracker over prepared real data.

Answers one question: does matching issuer credit lines per period reproduce a
MaxRewards-style tracker (used / partial / missed / at risk) on real statements?

Run:  uv run python prototype/tracker_proto.py [--as-of 2026-09-26]
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA_DIR = Path(os.environ.get("PERKWATCH_DATA_DIR", ROOT / "data" / "real"))
DB_PATH = DATA_DIR / "prepared" / "perkwatch.sqlite"
TIPS_PATH = DATA_DIR / "prototype" / "community_tips.json"
CARDS = json.loads((ROOT / "src" / "perk_watch" / "cards.json").read_text())

# Days before a period ends when unused value counts as "at risk".
AT_RISK_DAYS = {"monthly": 7, "quarterly": 14, "semiannual": 30, "annual": 45}
# A closed period stays "pending" until statements cover this many days past its end,
# because issuer credits usually post a few days after the purchase.
PENDING_GRACE_DAYS = 10


@dataclass
class Benefit:
    benefit_id: str          # reuses the V2 benefit_id so terms, embeddings and ideas join
    card_id: str
    title: str
    period: str              # monthly | quarterly | semiannual | annual
    amount_minor: int        # per period
    tracking: str            # auto | manual
    credit_pattern: str = ""  # regex over the statement description (case-insensitive)
    category: str = ""
    overrides: dict[int, int] = field(default_factory=dict)  # month -> amount for uneven periods


# Hand-checked catalog. Patterns marked "seen" matched real statement lines; the others
# follow the same "Platinum <name> Credit" naming and are unverified until a credit posts.
CATALOG = [
    Benefit("amex_platinum_300_digital_entertainment_credit", "amex_platinum", "$300 Digital Entertainment Credit",
            "monthly", 2500, "auto", r"platinum digital entertainment credit", "entertainment"),  # seen
    Benefit("amex_platinum_walmart_monthly_membership_credit", "amex_platinum", "Walmart+ Monthly Membership Credit",
            "monthly", 1295, "auto", r"platinum walmart", "shopping"),
    Benefit("amex_platinum_200_uber_cash", "amex_platinum", "$200 Uber Cash",
            "monthly", 1500, "manual", "", "travel", overrides={12: 3500}),
    Benefit("amex_platinum_400_resy_credit", "amex_platinum", "$400 Resy Credit",
            "quarterly", 10000, "auto", r"platinum resy credit", "dining"),  # seen
    Benefit("amex_platinum_300_lululemon_credit", "amex_platinum", "$300 lululemon Credit",
            "quarterly", 7500, "auto", r"platinum lululemon credit", "shopping"),  # seen
    Benefit("amex_platinum_600_hotel_credit", "amex_platinum", "$600 Hotel Credit",
            "semiannual", 30000, "auto", r"platinum (hotel|fhr|fine hotels)", "travel"),
    Benefit("amex_platinum_120_uber_one_credit", "amex_platinum", "$120 Uber One Credit",
            "annual", 12000, "auto", r"platinum uber one credit", "travel"),  # seen
    Benefit("amex_platinum_200_airline_fee_credit", "amex_platinum", "$200 Airline Fee Credit",
            "annual", 20000, "auto", r"platinum airline|airline fee credit", "travel"),
    Benefit("amex_platinum_200_oura_ring_credit", "amex_platinum", "$200 Oura Ring Credit",
            "annual", 20000, "auto", r"platinum oura", "wellness"),
    Benefit("amex_platinum_219_clear_credit", "amex_platinum", "$219 CLEAR+ Credit",
            "annual", 21900, "auto", r"platinum clear", "travel"),
    Benefit("amex_platinum_300_equinox_credit", "amex_platinum", "$300 Equinox Credit",
            "annual", 30000, "auto", r"platinum equinox", "wellness"),
    Benefit("chase_sapphire_preferred_benefit_010", "chase_sapphire_preferred", "$100 Chase Travel Hotel Credit",
            "annual", 10000, "auto", r"hotel credit|travel credit", "travel"),
    Benefit("chase_sapphire_preferred_benefit_001", "chase_sapphire_preferred", "$10 Monthly DoorDash Credit",
            "monthly", 1000, "manual", "", "dining"),
]
BY_ID = {b.benefit_id: b for b in CATALOG}


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    return date(value.year + month // 12, month % 12 + 1, 1)


def periods_for(benefit: Benefit, year: int, as_of: date) -> list[tuple[date, date, str]]:
    step = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}[benefit.period]
    out, start = [], date(year, 1, 1)
    while start <= as_of and start.year == year:
        end = _add_months(start, step) - timedelta(days=1)
        if step == 1:
            label = calendar.month_abbr[start.month]
        elif step == 3:
            label = f"Q{(start.month - 1) // 3 + 1}"
        elif step == 6:
            label = "H1" if start.month == 1 else "H2"
        else:
            label = str(year)
        out.append((start, end, label))
        start = end + timedelta(days=1)
    return out


def load_credits(db: sqlite3.Connection) -> dict[str, list[dict]]:
    """Match issuer credit lines to catalog benefits by description pattern and card sign."""
    matched: dict[str, list[dict]] = {b.benefit_id: [] for b in CATALOG}
    unmatched: list[str] = []
    for card_id, meta in CARDS.items():
        sign = -1 if meta["statement_credit_sign"] == "negative" else 1
        rows = db.execute(
            "SELECT transaction_id, posted_date, description, amount_minor FROM transactions "
            "WHERE card_id = ? AND lower(description) LIKE '%credit%'", (card_id,)).fetchall()
        for tid, posted, desc, amount in rows:
            if amount * sign <= 0:
                continue
            hit = next((b for b in CATALOG if b.card_id == card_id and b.credit_pattern
                        and re.search(b.credit_pattern, desc, re.I)), None)
            if hit:
                matched[hit.benefit_id].append({"transaction_id": tid, "date": posted, "amount_minor": abs(amount)})
            else:
                unmatched.append(card_id)
    matched["_unmatched_credit_lines"] = [{"card_id": c} for c in unmatched]
    return matched


def data_through(db: sqlite3.Connection) -> dict[str, str | None]:
    return {card: db.execute("SELECT MAX(posted_date) FROM transactions WHERE card_id = ?", (card,)).fetchone()[0]
            for card in CARDS}


def track(db: sqlite3.Connection, as_of: date, marks: dict[tuple[str, str], int] | None = None) -> dict:
    """Return every catalog benefit with its full period history and current status."""
    marks = marks or {}
    credits = load_credits(db)
    through = data_through(db)
    terms = dict(db.execute("SELECT benefit_id, terms FROM benefits").fetchall())
    benefits = []
    for b in CATALOG:
        covered = date.fromisoformat(through[b.card_id]) if through[b.card_id] else None
        periods = []
        for start, end, label in periods_for(b, as_of.year, as_of):
            amount = b.overrides.get(start.month, b.amount_minor) if b.period == "monthly" else b.amount_minor
            hits = [c for c in credits[b.benefit_id] if start.isoformat() <= c["date"] <= end.isoformat()]
            used = sum(c["amount_minor"] for c in hits) + marks.get((b.benefit_id, start.isoformat()), 0)
            used = min(used, amount)
            closed = end < as_of
            if used >= amount:
                status = "used"
            elif closed and b.tracking == "manual" and used == 0:
                status = "unmarked"  # can't see in-app credits on a statement; user must mark them
            elif closed and (covered is None or end + timedelta(days=PENDING_GRACE_DAYS) > covered):
                status = "pending"
            elif closed:
                status = "partial" if used else "missed"
            else:
                days_left = (end - as_of).days + 1
                status = "at_risk" if days_left <= AT_RISK_DAYS[b.period] else "open"
            periods.append({"label": label, "start": start.isoformat(), "end": end.isoformat(),
                            "amount_minor": amount, "used_minor": used, "status": status,
                            "credits": hits, "marked": (b.benefit_id, start.isoformat()) in marks})
        current = dict(periods[-1])
        current["days_left"] = (date.fromisoformat(current["end"]) - as_of).days + 1
        current["remaining_minor"] = current["amount_minor"] - current["used_minor"]
        captured = sum(p["used_minor"] for p in periods)
        missed = sum(p["amount_minor"] - p["used_minor"] for p in periods if p["status"] in {"missed", "partial"})
        benefits.append({
            "benefit_id": b.benefit_id, "card_id": b.card_id, "card": CARDS[b.card_id]["display_name"],
            "title": b.title, "period": b.period, "tracking": b.tracking, "category": b.category,
            "current": current, "periods": periods,
            "ytd": {"captured_minor": captured, "missed_minor": missed},
            "terms": terms.get(b.benefit_id, ""),
        })
    at_risk = sum(x["current"]["remaining_minor"] for x in benefits if x["current"]["status"] == "at_risk")
    return {
        "as_of": as_of.isoformat(), "data_through": through,
        "totals": {"captured_minor": sum(x["ytd"]["captured_minor"] for x in benefits),
                   "missed_minor": sum(x["ytd"]["missed_minor"] for x in benefits),
                   "at_risk_minor": at_risk},
        "unmatched_credit_lines": len(credits["_unmatched_credit_lines"]),
        "benefits": benefits,
    }


def load_tips() -> list[dict]:
    tips = json.loads(TIPS_PATH.read_text())["tips"] if TIPS_PATH.exists() else []
    return tips


def community_for(db: sqlite3.Connection, benefit_id: str) -> list[dict]:
    """Collected tips (prototype file) plus reviewed V2 community ideas for one benefit."""
    tips = [t for t in load_tips() if t.get("benefit_id") == benefit_id]
    for idea, url, source_date in db.execute(
            "SELECT idea, source_url, source_date FROM community_ideas WHERE benefit_id = ?", (benefit_id,)):
        tips.append({"benefit_id": benefit_id, "tip": idea, "source_url": url, "source_date": source_date})
    return tips


def open_db() -> sqlite3.Connection:
    return sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    result = track(open_db(), date.fromisoformat(args.as_of))
    money = lambda m: f"${m / 100:,.2f}"
    print(f"as of {result['as_of']}  data through {result['data_through']}")
    print("captured {} | missed {} | at risk now {} | unmatched credit lines {}".format(
        *(money(result["totals"][k]) for k in ("captured_minor", "missed_minor", "at_risk_minor")),
        result["unmatched_credit_lines"]))
    glyph = {"used": "●", "partial": "◐", "missed": "✗", "pending": "…", "unmarked": "?", "at_risk": "!", "open": "○"}
    for b in result["benefits"]:
        c = b["current"]
        dots = " ".join(f"{p['label']}{glyph[p['status']]}" for p in b["periods"])
        print(f"{b['title'][:36]:36} {money(c['used_minor']):>8} / {money(c['amount_minor']):<8} "
              f"{c['status']:8} {c['days_left']:>3}d  {dots}")
