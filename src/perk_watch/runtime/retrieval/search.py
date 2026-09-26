"""Search prepared official benefit text with production embeddings."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from ...embeddings import EmbeddingProvider, content_hash, idea_hash

_MIN_SCORE = 0.2


def _source_date(path: str) -> date | None:
    match = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", path)
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


class BenefitSearch:
    """Search official benefits using stored OpenAI embeddings."""

    def __init__(self, db: sqlite3.Connection, embedder: EmbeddingProvider | None = None):
        self.db = db
        self.embedder = embedder

    def _provider(self) -> EmbeddingProvider:
        if self.embedder is None:
            from ...embeddings import OpenAIEmbeddingProvider
            self.embedder = OpenAIEmbeddingProvider()
        return self.embedder

    def search(self, question: str, *, card_id: str | None = None,
               benefit_id: str | None = None, as_of: date | str | None = None,
               limit: int = 5) -> list[dict[str, object]]:
        if limit < 1:
            return []
        cutoff = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        clauses, params = [], []
        if card_id:
            clauses.append("b.card_id = ?")
            params.append(card_id)
        if benefit_id:
            clauses.append("b.benefit_id = ?")
            params.append(benefit_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.execute(
            f"SELECT b.benefit_id, b.card_id, c.display_name, b.title, b.terms, "
            f"b.source_id, s.path, e.model, e.vector_json, e.content_sha256 "
            f"FROM benefits b JOIN cards c ON c.card_id = b.card_id "
            f"JOIN sources s ON s.source_id = b.source_id "
            f"LEFT JOIN benefit_embeddings e ON e.benefit_id = b.benefit_id {where}", params).fetchall()
        candidates = []
        for row in rows:
            source_date = _source_date(row[6])
            if cutoff and source_date and source_date > cutoff:
                continue
            candidates.append(row)
        if not candidates:
            return []

        provider = self._provider()
        query_vector = provider.embed([question])[0]
        ranked = []
        for row in candidates:
            if row[8] is None or row[7] != provider.model or row[9] != content_hash(row[3], row[4]):
                continue
            vector = json.loads(row[8])
            score = _cosine(query_vector, vector)
            if score >= _MIN_SCORE:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1][2], item[1][0]))
        return [{"benefit_id": row[0], "card_id": row[1], "card": row[2],
                 "title": row[3], "text": row[4], "score": score,
                 "source_reference": {"source_id": row[5], "path": row[6]}}
                for score, row in ranked[:limit]]


class CommunitySearch:
    """Search prepared, current community ideas separately from official facts."""

    def __init__(self, db: sqlite3.Connection, embedder: EmbeddingProvider | None = None):
        self.db = db
        self.embedder = embedder

    def _provider(self) -> EmbeddingProvider:
        if self.embedder is None:
            from ...embeddings import OpenAIEmbeddingProvider
            self.embedder = OpenAIEmbeddingProvider()
        return self.embedder

    def search(self, question: str, *, card_id: str | None = None,
               benefit_id: str | None = None, limit: int = 5) -> list[dict[str, object]]:
        if limit < 1:
            return []
        clauses, params = ["i.source_date <> ''"], []
        if card_id:
            clauses.append("i.card_id = ?")
            params.append(card_id)
        if benefit_id:
            clauses.append("i.benefit_id = ?")
            params.append(benefit_id)
        rows = self.db.execute(
            "SELECT i.idea_id, i.card_id, c.display_name, i.benefit_id, b.title, i.idea, i.excerpt, "
            "i.source_url, i.source_date, e.model, e.vector_json, e.content_sha256 "
            "FROM community_ideas i JOIN benefits b ON b.benefit_id = i.benefit_id "
            "JOIN cards c ON c.card_id = i.card_id "
            "LEFT JOIN community_embeddings e ON e.idea_id = i.idea_id WHERE " + " AND ".join(clauses), params
        ).fetchall()
        if not rows:
            return []
        provider = self._provider()
        query_vector = provider.embed([question])[0]
        ranked = []
        for row in rows:
            if row[10] is None or row[9] != provider.model or row[11] != idea_hash(row[5], row[6]):
                continue
            vector = json.loads(row[10])
            score = _cosine(query_vector, vector)
            if score >= _MIN_SCORE:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1][2], item[1][0]))
        return [{"idea_id": row[0], "card_id": row[1], "card": row[2], "benefit_id": row[3],
                 "benefit": row[4], "idea": row[5], "excerpt": row[6], "source_url": row[7],
                 "source_date": row[8], "label": "Community suggestion", "score": score}
                for score, row in ranked[:limit]]


def search_community_ideas(db: sqlite3.Connection, question: str, **filters: object) -> list[dict[str, object]]:
    return CommunitySearch(db, filters.pop("embedder", None)).search(question, **filters)


def search_benefits(db: sqlite3.Connection, question: str, **filters: object) -> list[dict[str, object]]:
    return BenefitSearch(db, filters.pop("embedder", None)).search(question, **filters)
