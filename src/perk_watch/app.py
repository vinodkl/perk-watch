"""Read-only application functions for prepared PerkWatch data."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .agent import answer_with_db
from .calculations import calculate_all, calculate_benefit
from .search import search_benefits


def database(root: str | Path | None = None) -> sqlite3.Connection:
    data_root = Path(root or os.environ.get("PERKWATCH_DATA_DIR", "data/real"))
    path = data_root / "prepared" / "perkwatch.sqlite"
    if not path.exists():
        raise FileNotFoundError(f"prepared data not found: {path}")
    return sqlite3.connect(path)


def show_benefits(root: str | Path | None = None, **filters: object) -> list[dict[str, object]]:
    db = database(root)
    try:
        return calculate_all(db, **filters)
    finally:
        db.close()


def benefit_status(root: str | Path | None, benefit_id: str, **filters: object) -> dict[str, object]:
    db = database(root)
    try:
        return calculate_benefit(db, benefit_id, **filters)
    finally:
        db.close()


def find_benefits(root: str | Path | None, question: str, **filters: object) -> list[dict[str, object]]:
    db = database(root)
    try:
        return search_benefits(db, question, **filters)
    finally:
        db.close()


def answer(question: str, root: str | Path | None = None, *, client=None,
           model: str = "gpt-4o-mini") -> str:
    db = database(root)
    try:
        return answer_with_db(db, question, client=client, model=model)
    finally:
        db.close()
