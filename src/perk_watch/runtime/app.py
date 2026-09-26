"""Read-only application functions for prepared PerkWatch data."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .agent import answer_with_db


def database(root: str | Path | None = None) -> sqlite3.Connection:
    data_root = Path(root or os.environ.get("PERKWATCH_DATA_DIR", "data/real"))
    path = data_root / "prepared" / "perkwatch.sqlite"
    if not path.exists():
        raise FileNotFoundError(f"prepared data not found: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def answer(question: str, root: str | Path | None = None, *, client=None,
           model: str = "gpt-4o-mini") -> str:
    db = database(root)
    try:
        return answer_with_db(db, question, client=client, model=model)
    finally:
        db.close()
