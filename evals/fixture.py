"""Build a synthetic SQLite dataset for evaluation; never reads real card data."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from perk_watch.prepare.storage import SCHEMA
from perk_watch.prepare.rag_search_index import build_benefit_embeddings, build_community_embeddings


class FixtureEmbedder:
    """Deterministic word-vector provider; no external embedding calls."""
    model = "fixture-word-count-v1"
    words = ("airline", "fee", "credit", "travel", "hotel", "purchase", "monthly",
             "dining", "quarterly", "yearly", "calendar", "account", "year", "reset",
             "refund", "transaction", "merchant", "community", "suggestion", "eligible",
             "incidental", "unknown", "terms", "benefit", "cover", "booking")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.lower().count(word)) for word in self.words] for text in texts]


def build_fixture(db: sqlite3.Connection) -> sqlite3.Connection:
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO cards VALUES (?, ?)", [
        ("fixture:amex", "Synthetic Amex"), ("fixture:chase", "Synthetic Chase")])
    sources = [
        ("fixture:airline-fee-terms", "fixture:amex", "benefits", "airline-fee-terms.json", "synthetic"),
        ("fixture:travel-credit-terms", "fixture:amex", "benefits", "travel-credit-terms.json", "synthetic"),
        ("fixture:monthly-credit-terms", "fixture:amex", "benefits", "monthly-credit-terms.json", "synthetic"),
        ("fixture:unclear-credit-terms", "fixture:amex", "benefits", "unclear-credit-terms.json", "synthetic"),
        ("fixture:quarterly-credit-terms", "fixture:amex", "benefits", "quarterly-credit-terms.json", "synthetic"),
        ("fixture:yearly-credit-terms", "fixture:amex", "benefits", "yearly-credit-terms.json", "synthetic"),
        ("fixture:account-year-credit-terms", "fixture:amex", "benefits", "account-year-credit-terms.json", "synthetic"),
        ("fixture:incomplete-credit-terms", "fixture:amex", "benefits", "incomplete-credit-terms.json", "synthetic"),
        ("fixture:community-source", "fixture:amex", "community", "community.json", "synthetic"),
    ]
    db.executemany("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", sources)
    benefits = [
        ("fixture:travel-credit", "fixture:amex", "Travel credit", 10000, "yearly", "airline,hotel", 0, 0,
         "Synthetic travel benefit terms.", "fixture:travel-credit-terms"),
        ("fixture:monthly-credit", "fixture:amex", "Monthly dining credit", 5000, "monthly", "dining", 0, 0,
         "Synthetic monthly credit terms.", "fixture:monthly-credit-terms"),
        ("fixture:unclear-credit", "fixture:chase", "Unclear merchant credit", 5000, "monthly", "dining", 0, 0,
         "Synthetic terms used to test unknown merchant eligibility.", "fixture:unclear-credit-terms"),
        ("fixture:quarterly-credit", "fixture:amex", "Quarterly credit", 10000, "quarterly", "dining", 0, 0,
         "Synthetic quarterly credit terms.", "fixture:quarterly-credit-terms"),
        ("fixture:yearly-credit", "fixture:amex", "Calendar-year credit", 10000, "yearly", "travel", 0, 0,
         "Synthetic yearly credit terms.", "fixture:yearly-credit-terms"),
        ("fixture:account-year-credit", "fixture:amex", "Account-year credit", 10000, "account_year", "travel", 0, 0,
         "Synthetic account-year credit terms.", "fixture:account-year-credit-terms"),
        ("fixture:incomplete-credit", "fixture:amex", "Incomplete credit", None, "monthly", "", 0, 0,
         "Synthetic terms with unknown amount and eligibility.", "fixture:incomplete-credit-terms"),
        ("fixture:airline-fee", "fixture:amex", "Airline fee credit", 20000, "yearly", "airline", 1, 0,
         "Synthetic airline fee credit terms for eligible incidental fees.", "fixture:airline-fee-terms"),
    ]
    db.executemany("INSERT INTO benefits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", benefits)
    transactions = [
        ("fixture:travel-purchase", "fixture:amex", "2026-05-01", "Synthetic travel purchase", 2000, "USD", "hotel", "fixture:travel-credit-terms"),
        ("fixture:purchase", "fixture:amex", "2026-10-05", "Synthetic dining purchase", 2000, "USD", "dining", "fixture:monthly-credit-terms"),
        ("fixture:refund", "fixture:amex", "2026-10-10", "Synthetic dining refund", -2000, "USD", "dining", "fixture:monthly-credit-terms"),
        ("fixture:unknown-merchant", "fixture:chase", "2026-10-11", "Synthetic unclear purchase", 1000, "USD", None, "fixture:unclear-credit-terms"),
    ]
    db.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", transactions)
    db.execute("INSERT INTO community_ideas VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
        "fixture:idea-1", "fixture:amex", "fixture:travel-credit",
        "Consider using the travel credit for an eligible hotel stay.", "Synthetic community paraphrase.",
        "https://example.test/community/1", "synthetic-v1", "2026-09-01"))
    embedder = FixtureEmbedder()
    build_benefit_embeddings(db, embedder)
    build_community_embeddings(db, embedder)
    db.commit()
    return db


def open_fixture(path: str | Path = ":memory:") -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).unlink(missing_ok=True)
    return build_fixture(sqlite3.connect(path))


if __name__ == "__main__":
    target = Path(__file__).with_name("fixture.sqlite")
    if target.exists():
        target.unlink()
    open_fixture(target).close()
    print(target)
