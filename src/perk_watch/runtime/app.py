"""Read-only access to prepared PerkWatch data."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def data_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("PERKWATCH_DATA_DIR", "data/real"))


def database(root: str | Path | None = None) -> sqlite3.Connection:
    path = data_root(root) / "prepared" / "perkwatch.sqlite"
    if not path.exists():
        raise FileNotFoundError(f"prepared data not found: {path}")
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    db.execute("PRAGMA busy_timeout = 1000")
    db.execute("PRAGMA query_only = ON")
    return db
