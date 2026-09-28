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
CREATE TABLE IF NOT EXISTS community_ideas (
  idea_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
  benefit_id TEXT NOT NULL, idea TEXT NOT NULL, excerpt TEXT NOT NULL,
  source_url TEXT NOT NULL, terms_version TEXT NOT NULL, source_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS community_embeddings (
  idea_id TEXT PRIMARY KEY REFERENCES community_ideas(idea_id),
  model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS community_tips (
  tip_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
  benefit_id TEXT NOT NULL, tip TEXT NOT NULL, source_url TEXT NOT NULL,
  source_title TEXT NOT NULL DEFAULT '', source_date TEXT NOT NULL DEFAULT '',
  last_verified TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS community_tip_embeddings (
  tip_id TEXT PRIMARY KEY REFERENCES community_tips(tip_id),
  model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS community_blurbs (
  benefit_id TEXT PRIMARY KEY, blurb TEXT NOT NULL, model TEXT NOT NULL,
  tips_sha256 TEXT NOT NULL
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
    # Older databases carry match tables whose foreign keys would block replacing transactions;
    # the tracker now matches credit lines against catalog.json at read time instead.
    db.execute("DROP TABLE IF EXISTS merchant_matches")
    db.execute("DROP TABLE IF EXISTS credit_matches")
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(community_ideas)")}
    if "source_date" not in columns:
        db.execute("ALTER TABLE community_ideas ADD COLUMN source_date TEXT NOT NULL DEFAULT ''")
    benefit_columns = {row[1] for row in db.execute("PRAGMA table_info(benefits)")}
    if "mechanism" not in benefit_columns:
        db.execute("ALTER TABLE benefits ADD COLUMN mechanism TEXT NOT NULL DEFAULT 'statement_credit'")
    return db


def replace_card_data(db: sqlite3.Connection, card_id: str, display_name: str,
                      sources: Iterable[Mapping[str, object]], benefits: Iterable[Mapping[str, object]],
                      transactions: Iterable[Mapping[str, object]], ideas: Iterable[Mapping[str, object]],
                      tips: Iterable[Mapping[str, object]] = ()) -> None:
    db.execute("DELETE FROM transactions WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM benefit_embeddings WHERE benefit_id IN (SELECT benefit_id FROM benefits WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM benefits WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM community_embeddings WHERE idea_id IN (SELECT idea_id FROM community_ideas WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM community_ideas WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM community_tip_embeddings WHERE tip_id IN (SELECT tip_id FROM community_tips WHERE card_id = ?)", (card_id,))
    db.execute("DELETE FROM community_tips WHERE card_id = ?", (card_id,))
    db.execute("DELETE FROM sources WHERE card_id = ?", (card_id,))
    db.execute("INSERT OR REPLACE INTO cards VALUES (?, ?)", (card_id, display_name))
    for row in sources:
        db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?)", tuple(row[k] for k in ("source_id", "card_id", "kind", "path", "content_sha256")))
    for row in benefits:
        db.execute("INSERT OR REPLACE INTO benefits (benefit_id, card_id, title, amount_minor, period, eligible_merchants, enrollment_required, booking_required, terms, source_id, mechanism) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["benefit_id"], card_id, row["title"], row["amount_minor"], row["period"],
                    row["eligible_merchants"], row["enrollment_required"], row["booking_required"], row["terms"], row["source_id"], row.get("mechanism", "statement_credit")))
    for row in transactions:
        db.execute("INSERT OR REPLACE INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["transaction_id"], card_id, row["posted_date"], row["description"], row["amount_minor"], row["currency"], row.get("merchant"), row["source_id"]))
    for row in ideas:
        db.execute("INSERT OR REPLACE INTO community_ideas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["idea_id"], card_id, row["benefit_id"], row["idea"], row["excerpt"], row["source_url"], row["terms_version"], row.get("source_date", "")))
    for row in tips:
        db.execute("INSERT OR REPLACE INTO community_tips (tip_id, card_id, benefit_id, tip, source_url, source_title, source_date, last_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["tip_id"], card_id, row["benefit_id"], row["tip"], row["source_url"], row.get("source_title", ""), row.get("source_date", ""), row.get("last_verified", "")))
