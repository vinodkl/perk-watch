"""Build stored benefit and community vectors during offline preparation."""
from __future__ import annotations

import json
import sqlite3

from ..embeddings import EmbeddingProvider, content_hash, idea_hash


def build_community_embeddings(db: sqlite3.Connection, embedder: EmbeddingProvider,
                               card_id: str | None = None,
                               reuse: dict[str, tuple[str, int, str]] | None = None) -> int:
    """`reuse` (see `snapshot_embeddings_by_hash`) carries forward vectors for unchanged idea+excerpt text."""
    query = ("SELECT idea_id, idea, excerpt FROM community_ideas WHERE card_id = ? ORDER BY idea_id"
             if card_id else "SELECT idea_id, idea, excerpt FROM community_ideas ORDER BY idea_id")
    rows = db.execute(query, (card_id,) if card_id else ()).fetchall()
    if not rows:
        return 0
    reuse = reuse or {}
    hashes = [idea_hash(idea, excerpt) for _, idea, excerpt in rows]
    fresh = [index for index, digest in enumerate(hashes)
             if not (digest in reuse and reuse[digest][0] == embedder.model)]
    vectors_by_index: dict[int, list[float]] = {}
    if fresh:
        vectors = embedder.embed([f"{rows[index][1]}\n{rows[index][2]}" for index in fresh])
        if len(vectors) != len(fresh):
            raise ValueError("embedding provider returned the wrong number of vectors")
        vectors_by_index = dict(zip(fresh, vectors))
    for index, ((idea_id, idea, excerpt), digest) in enumerate(zip(rows, hashes)):
        if index in vectors_by_index:
            model, dimensions, vector_json = embedder.model, len(vectors_by_index[index]), json.dumps(vectors_by_index[index])
        else:
            model, dimensions, vector_json = reuse[digest]
        db.execute("INSERT OR REPLACE INTO community_embeddings VALUES (?, ?, ?, ?, ?)",
                   (idea_id, model, dimensions, vector_json, digest))
    return len(rows)


def build_community_tip_embeddings(db: sqlite3.Connection, embedder: EmbeddingProvider,
                                   card_id: str | None = None,
                                   reuse: dict[str, tuple[str, int, str]] | None = None) -> int:
    """Embed collected community tips (`community_tips`) so they are searchable the same way ideas are.

    `reuse` (see `snapshot_embeddings_by_hash`) carries forward vectors for unchanged tip text.
    """
    query = ("SELECT tip_id, tip, source_url FROM community_tips WHERE card_id = ? ORDER BY tip_id"
             if card_id else "SELECT tip_id, tip, source_url FROM community_tips ORDER BY tip_id")
    rows = db.execute(query, (card_id,) if card_id else ()).fetchall()
    if not rows:
        return 0
    reuse = reuse or {}
    hashes = [idea_hash(tip, source_url) for _, tip, source_url in rows]
    fresh = [index for index, digest in enumerate(hashes)
             if not (digest in reuse and reuse[digest][0] == embedder.model)]
    vectors_by_index: dict[int, list[float]] = {}
    if fresh:
        vectors = embedder.embed([rows[index][1] for index in fresh])
        if len(vectors) != len(fresh):
            raise ValueError("embedding provider returned the wrong number of vectors")
        vectors_by_index = dict(zip(fresh, vectors))
    for index, ((tip_id, tip, source_url), digest) in enumerate(zip(rows, hashes)):
        if index in vectors_by_index:
            model, dimensions, vector_json = embedder.model, len(vectors_by_index[index]), json.dumps(vectors_by_index[index])
        else:
            model, dimensions, vector_json = reuse[digest]
        db.execute("INSERT OR REPLACE INTO community_tip_embeddings VALUES (?, ?, ?, ?, ?)",
                   (tip_id, model, dimensions, vector_json, digest))
    return len(rows)


def snapshot_embeddings_by_hash(db: sqlite3.Connection, table: str) -> dict[str, tuple[str, int, str]]:
    """Read every stored vector in `table` keyed by its content hash, for carrying forward
    across a delete-and-reinsert cycle when the underlying text has not changed."""
    return {content_sha256: (model, dimensions, vector_json) for model, dimensions, vector_json, content_sha256 in
            db.execute(f"SELECT model, dimensions, vector_json, content_sha256 FROM {table}")}


def build_benefit_embeddings(db: sqlite3.Connection, embedder: EmbeddingProvider,
                             card_id: str | None = None,
                             reuse: dict[str, tuple[str, int, str]] | None = None) -> int:
    """Generate and persist embeddings for prepared benefits.

    `reuse` (benefit content hash -> (model, dimensions, vector_json), see
    `snapshot_embeddings_by_hash`) lets a caller carry forward vectors for benefits whose
    title+terms text has not changed, so unchanged text is not re-embedded.
    """
    if card_id:
        rows = db.execute("SELECT benefit_id, title, terms FROM benefits WHERE card_id = ? ORDER BY benefit_id",
                          (card_id,)).fetchall()
    else:
        rows = db.execute("SELECT benefit_id, title, terms FROM benefits ORDER BY benefit_id").fetchall()
    if not rows:
        return 0
    reuse = reuse or {}
    hashes = [content_hash(title, terms) for _, title, terms in rows]
    fresh = [index for index, digest in enumerate(hashes)
             if not (digest in reuse and reuse[digest][0] == embedder.model)]
    vectors_by_index: dict[int, list[float]] = {}
    if fresh:
        vectors = embedder.embed([f"{rows[index][1]}\n{rows[index][2]}" for index in fresh])
        if len(vectors) != len(fresh):
            raise ValueError("embedding provider returned the wrong number of vectors")
        vectors_by_index = dict(zip(fresh, vectors))
    for index, ((benefit_id, title, terms), digest) in enumerate(zip(rows, hashes)):
        if index in vectors_by_index:
            model, dimensions, vector_json = embedder.model, len(vectors_by_index[index]), json.dumps(vectors_by_index[index])
        else:
            model, dimensions, vector_json = reuse[digest]
        db.execute("INSERT OR REPLACE INTO benefit_embeddings VALUES (?, ?, ?, ?, ?)",
                   (benefit_id, model, dimensions, vector_json, digest))
    return len(rows)
