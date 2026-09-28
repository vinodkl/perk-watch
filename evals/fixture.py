"""Synthetic SQLite wallet for the tracker and chat evals. Never reads real card data."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from perk_watch.catalog import load_catalog
from perk_watch.prepare.rag_search_index import (
    build_benefit_embeddings, build_community_embeddings, build_community_tip_embeddings)
from perk_watch.prepare.storage import connect

AMEX, CHASE, RESERVE = "amex_platinum", "chase_sapphire_preferred", "chase_sapphire_reserve"

# (card_id, posted_date, description, amount_minor) in each card's export sign:
# Amex credits are negative, Chase credits are positive.
STATEMENT_LINES = [
    # Digital Entertainment (monthly $25): partial Jan, used Feb, missed Mar, two lines add up in Apr.
    (AMEX, "2026-01-11", "Platinum Digital Entertainment Credit", -2299),
    (AMEX, "2026-02-11", "Platinum Digital Entertainment Credit", -2500),
    (AMEX, "2026-04-08", "Platinum Digital Entertainment Credit", -1000),
    (AMEX, "2026-04-19", "Platinum Digital Entertainment Credit", -1500),
    (AMEX, "2026-05-12", "Platinum Digital Entertainment Credit", -2500),
    (AMEX, "2026-07-10", "Platinum Digital Entertainment Credit", -2500),
    # Resy (quarterly $100): used Q1, partial Q2, nothing yet in Q3.
    (AMEX, "2026-03-28", "Platinum Resy Credit", -10000),
    (AMEX, "2026-05-20", "PLATINUM RESY CREDIT", -5000),
    (AMEX, "2026-05-18", "RESY RESTAURANT PURCHASE", 5000),  # the purchase, not the credit
    # lululemon (quarterly $75): missed Q1, used Q2 and Q3.
    (AMEX, "2026-06-02", "Platinum Lululemon Credit", -7500),
    (AMEX, "2026-08-14", "Platinum Lululemon Credit", -7500),
    # Hotel (semiannual $300): partial H1.
    (AMEX, "2026-03-03", "Platinum Hotel Credit", -20000),
    # Lines that mention "credit" but are not a tracked benefit.
    (AMEX, "2026-02-20", "Platinum Mystery Credit", -1000),     # unmatched issuer credit
    (AMEX, "2026-06-15", "CREDIT KARMA SUBSCRIPTION", 999),     # purchase sign: ignored
    # Amex statements stop here, so August closes as "pending" rather than "missed".
    (AMEX, "2026-09-05", "COFFEE SHOP", 700),
    # Chase hotel credit posts positive; a negative "credit" line is a reversal and is ignored.
    (CHASE, "2026-05-02", "CHASE TRAVEL HOTEL CREDIT", 10000),
    (CHASE, "2026-05-03", "HOTEL CREDIT REVERSAL", -10000),
    (CHASE, "2026-09-20", "GROCERY STORE", -4500),
]

# Short, synthetic terms so chat and search have official text to cite.
TERMS = {
    "amex_platinum_300_digital_entertainment_credit": "Up to $25 back each month on eligible streaming and digital subscriptions such as Disney+, Hulu, ESPN+, Peacock, The New York Times and YouTube Premium. Enrollment required.",
    "amex_platinum_walmart_monthly_membership_credit": "Statement credit covering one monthly Walmart+ membership when paid with the card.",
    "amex_platinum_200_uber_cash": "Up to $15 in Uber Cash each month for rides or Uber Eats orders in the US, plus a $20 bonus in December. Uber Cash appears in the Uber app and expires at month end.",
    "amex_platinum_400_resy_credit": "Up to $100 in statement credits each calendar quarter for dining at US Resy restaurants. Enrollment required.",
    "amex_platinum_300_lululemon_credit": "Up to $75 each quarter at US lululemon stores and lululemon.com for athletic clothing. Enrollment required.",
    "amex_platinum_600_hotel_credit": "Up to $300 back twice a year on prepaid Fine Hotels + Resorts or Hotel Collection bookings through Amex Travel.",
    "amex_platinum_120_uber_one_credit": "Up to $120 per year in statement credits for an auto-renewing Uber One membership.",
    "amex_platinum_200_airline_fee_credit": "Up to $200 per year for incidental fees, such as checked bag fees, on one selected airline. Enrollment required.",
    "amex_platinum_200_oura_ring_credit": "Up to $200 per year toward an Oura Ring purchase. Enrollment required.",
    "amex_platinum_219_clear_credit": "Up to $219 per year for a CLEAR+ membership, the airport security fast lane that uses biometrics to skip the ID line.",
    "amex_platinum_300_equinox_credit": "Up to $300 per year toward an Equinox gym membership or the Equinox+ app. Enrollment required.",
    "chase_sapphire_preferred_benefit_010": "Up to $100 back each year on hotel stays booked through Chase Travel.",
    "chase_sapphire_preferred_benefit_001": "Up to $10 each month in DoorDash promotions on non-restaurant orders. Activate DashPass to use it.",
    "chase_sapphire_reserve_300_travel_credit": "Up to $300 back each year, automatically applied to travel purchases charged to the card.",
    "chase_sapphire_reserve_500_edit_hotel_credit": "Up to $250 in statement credits per qualifying prepaid stay of two nights or more booked through The Edit, on up to two bookings a year.",
    "chase_sapphire_reserve_300_dining_credit": "Up to $150 back each half of the year on dining at Sapphire Reserve Exclusive Tables restaurants.",
    "chase_sapphire_reserve_300_stubhub_credit": "Up to $150 back each half of the year on tickets bought through StubHub or viagogo.",
    "chase_sapphire_reserve_25_doordash_credit": "Up to $25 each month in DoorDash promotions with an active DashPass membership.",
    "chase_sapphire_reserve_10_lyft_credit": "Up to $10 in monthly in-app Lyft ride credits.",
    "chase_sapphire_reserve_10_peloton_credit": "Up to $10 back each month on an eligible Peloton membership.",
}

COMMUNITY_IDEAS = [
    ("idea-resy-1", AMEX, "amex_platinum_400_resy_credit",
     "Some cardholders buy a restaurant gift card at a Resy venue near the end of the quarter.",
     "Synthetic paraphrase.", "https://example.test/community/resy-1", "synthetic-v1", "2026-08-01"),
]

# (tip_id, card_id, benefit_id, tip, source_url, source_title, source_date, last_verified)
COMMUNITY_TIPS = [
    ("tip-equinox-1", AMEX, "amex_platinum_300_equinox_credit",
     "Ask the gym front desk to manually apply the Equinox+ app membership if the credit does not auto-post.",
     "https://example.test/community/equinox-1", "Synthetic forum thread", "2026-07-15", "2026-08-01"),
]


class FixtureEmbedder:
    """Deterministic keyword vectors, so fixture search needs no network."""
    model = "fixture-keywords-v1"
    words = ("streaming", "disney", "walmart", "uber", "dining", "restaurant", "resy", "lululemon",
             "athletic", "hotel", "airline", "bag", "oura", "clear", "airport", "security", "fast",
             "gym", "equinox", "doordash", "chase", "travel", "quarter", "month", "year")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.lower().count(word)) for word in self.words] for text in texts]


def build_fixture(path: str | Path = ":memory:") -> sqlite3.Connection:
    db = connect(path)
    db.executemany("INSERT INTO cards VALUES (?, ?)",
                   [(AMEX, "Amex Platinum"), (CHASE, "Chase Sapphire Preferred"), (RESERVE, "Chase Sapphire Reserve")])
    db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)",
                   [(f"s-{c}-tx", c, "transactions", f"{c}-synthetic.csv", "synthetic") for c in (AMEX, CHASE, RESERVE)]
                   + [(f"s-{c}-terms", c, "benefits", f"{c}-terms.json", "synthetic") for c in (AMEX, CHASE, RESERVE)])
    db.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, 'USD', NULL, ?)",
                   [(f"t{i:02d}", card, posted, desc, amount, f"s-{card}-tx")
                    for i, (card, posted, desc, amount) in enumerate(STATEMENT_LINES)])
    db.executemany(
        "INSERT INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, "
        "enrollment_required, booking_required, terms, source_id) VALUES (?, ?, ?, ?, ?, '', ?, 0, ?, ?)",
        [(b.benefit_id, b.card_id, b.title, b.amount_minor, b.period, int(b.enrollment_required),
          TERMS[b.benefit_id], f"s-{b.card_id}-terms") for b in load_catalog()])
    db.executemany("INSERT INTO community_ideas VALUES (?, ?, ?, ?, ?, ?, ?, ?)", COMMUNITY_IDEAS)
    db.executemany("INSERT INTO community_tips VALUES (?, ?, ?, ?, ?, ?, ?, ?)", COMMUNITY_TIPS)
    embedder = FixtureEmbedder()
    build_benefit_embeddings(db, embedder)
    build_community_embeddings(db, embedder)
    build_community_tip_embeddings(db, embedder)
    db.commit()
    return db
