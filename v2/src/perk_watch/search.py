"""Search prepared official benefit text without touching transaction data."""
from __future__ import annotations

import re
import sqlite3
from datetime import date


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1}


def _source_date(path: str) -> date | None:
    match = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", path)
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


class BenefitSearch:
    """Small local ranked search over official benefit text."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

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
            f"b.source_id, s.path FROM benefits b JOIN cards c ON c.card_id = b.card_id "
            f"JOIN sources s ON s.source_id = b.source_id {where}", params).fetchall()
        query = _words(question)
        ranked = []
        for row in rows:
            source_date = _source_date(row[6])
            if cutoff and source_date and source_date > cutoff:
                continue
            words = _words(f"{row[3]} {row[4]}")
            overlap = len(query & words)
            if not overlap:
                continue
            # IDF keeps common words from dominating the small local corpus.
            ranked.append((overlap / (1 + len(words)), row))
        ranked.sort(key=lambda item: (-item[0], item[1][2], item[1][0]))
        return [{"benefit_id": row[0], "card_id": row[1], "card": row[2],
                 "title": row[3], "text": row[4],
                 "source_reference": {"source_id": row[5], "path": row[6]}}
                for _, row in ranked[:limit]]


def search_benefits(db: sqlite3.Connection, question: str, **filters: object) -> list[dict[str, object]]:
    return BenefitSearch(db).search(question, **filters)
