"""Build stored benefit and community vectors during offline preparation."""
from __future__ import annotations

import json
import sqlite3

from ..embeddings import EmbeddingProvider, content_hash, idea_hash


def build_community_embeddings(db: sqlite3.Connection, embedder: EmbeddingProvider,
                               card_id: str | None = None) -> int:
    query = ("SELECT idea_id, idea, excerpt FROM community_ideas WHERE card_id = ? ORDER BY idea_id"
             if card_id else "SELECT idea_id, idea, excerpt FROM community_ideas ORDER BY idea_id")
    rows = db.execute(query, (card_id,) if card_id else ()).fetchall()
    vectors = embedder.embed([f"{idea}\n{excerpt}" for _, idea, excerpt in rows]) if rows else []
    if len(vectors) != len(rows):
        raise ValueError("embedding provider returned the wrong number of vectors")
    for (idea_id, idea, excerpt), vector in zip(rows, vectors):
        db.execute("INSERT OR REPLACE INTO community_embeddings VALUES (?, ?, ?, ?, ?)",
                   (idea_id, embedder.model, len(vector), json.dumps(vector), idea_hash(idea, excerpt)))
    return len(rows)


def build_benefit_embeddings(db: sqlite3.Connection, embedder: EmbeddingProvider,
                             card_id: str | None = None) -> int:
    """Generate and persist embeddings for prepared benefits."""
    if card_id:
        rows = db.execute("SELECT benefit_id, title, terms FROM benefits WHERE card_id = ? ORDER BY benefit_id",
                          (card_id,)).fetchall()
    else:
        rows = db.execute("SELECT benefit_id, title, terms FROM benefits ORDER BY benefit_id").fetchall()
    if not rows:
        return 0
    vectors = embedder.embed([f"{title}\n{terms}" for _, title, terms in rows])
    if len(vectors) != len(rows):
        raise ValueError("embedding provider returned the wrong number of vectors")
    for (benefit_id, title, terms), vector in zip(rows, vectors):
        db.execute("INSERT OR REPLACE INTO benefit_embeddings VALUES (?, ?, ?, ?, ?)",
                   (benefit_id, embedder.model, len(vector), json.dumps(vector), content_hash(title, terms)))
    return len(rows)
