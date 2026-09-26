"""SQLite schema and writes for prepared V2 local data."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY, card_id TEXT NOT NULL, kind TEXT NOT NULL,
  path TEXT NOT NULL, content_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
  card_id TEXT PRIMARY KEY, display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benefits (
  benefit_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
  title TEXT NOT NULL, amount_minor INTEGER, period TEXT, eligible_merchants TEXT,
  enrollment_required INTEGER, booking_required INTEGER, terms TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS transactions (
  transaction_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
  posted_date TEXT NOT NULL, description TEXT NOT NULL, amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL, merchant TEXT, source_id TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS merchant_matches (
  transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id),
  merchant TEXT, confidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_matches (
  transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id),
  benefit_id TEXT NOT NULL REFERENCES benefits(benefit_id), confidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS community_ideas (
  idea_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
  benefit_id TEXT NOT NULL, idea TEXT NOT NULL, excerpt TEXT NOT NULL,
  source_url TEXT NOT NULL, terms_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benefit_embeddings (
  benefit_id TEXT PRIMARY KEY REFERENCES benefits(benefit_id),
  model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def replace_card_data(db: sqlite3.Connection, card_id: str, display_name: str,
                      sources: Iterable[Mapping[str, object]], benefits: Iterable[Mapping[str, object]],
                      transactions: Iterable[Mapping[str, object]], matches: Iterable[Mapping[str, object]],
                      credit_matches: Iterable[Mapping[str, object]], ideas: Iterable[Mapping[str, object]]) -> None:
    db.execute("DELETE FROM credit_matches WHERE transaction_id IN (SELECT transaction_id FROM transactions WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM merchant_matches WHERE transaction_id IN (SELECT transaction_id FROM transactions WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM transactions WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM benefit_embeddings WHERE benefit_id IN (SELECT benefit_id FROM benefits WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM benefits WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM community_ideas WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM sources WHERE card_id = ?", (card_id,))
    db.execute("INSERT OR REPLACE INTO cards VALUES (?, ?)", (card_id, display_name))
    for row in sources:
        db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?)", tuple(row[k] for k in ("source_id", "card_id", "kind", "path", "content_sha256")))
    for row in benefits:
        db.execute("INSERT OR REPLACE INTO benefits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["benefit_id"], card_id, row["title"], row["amount_minor"], row["period"],
                    row["eligible_merchants"], row["enrollment_required"], row["booking_required"], row["terms"], row["source_id"]))
    for row in transactions:
        db.execute("INSERT OR REPLACE INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["transaction_id"], card_id, row["posted_date"], row["description"], row["amount_minor"], row["currency"], row["merchant"], row["source_id"]))
    for row in matches:
        db.execute("INSERT OR REPLACE INTO merchant_matches VALUES (?, ?, ?)", (row["transaction_id"], row["merchant"], row["confidence"]))
    for row in credit_matches:
        db.execute("INSERT OR REPLACE INTO credit_matches VALUES (?, ?, ?)",
                   (row["transaction_id"], row["benefit_id"], row["confidence"]))
    for row in ideas:
        db.execute("INSERT OR REPLACE INTO community_ideas VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (row["idea_id"], card_id, row["benefit_id"], row["idea"], row["excerpt"], row["source_url"], row["terms_version"]))
