"""Read prepared community tips and blurbs. Tips are suggestions, never official rules."""
from __future__ import annotations

import sqlite3


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def tips_for(db: sqlite3.Connection, benefit_id: str) -> list[dict[str, str]]:
    """Collected tips plus reviewed V2 community ideas for one benefit."""
    tips = []
    if _has_table(db, "community_tips"):
        tips += [{"tip": tip, "source_url": url, "source_title": title, "source_date": source_date, "last_verified": verified}
                 for tip, url, title, source_date, verified in db.execute(
                     "SELECT tip, source_url, source_title, source_date, last_verified FROM community_tips "
                     "WHERE benefit_id = ? ORDER BY tip_id", (benefit_id,))]
    tips += [{"tip": idea, "source_url": url, "source_title": "", "source_date": source_date, "last_verified": ""}
             for idea, url, source_date in db.execute(
                 "SELECT idea, source_url, source_date FROM community_ideas WHERE benefit_id = ? ORDER BY idea_id",
                 (benefit_id,))]
    return tips


def blurb_for(db: sqlite3.Connection, benefit_id: str) -> str:
    if not _has_table(db, "community_blurbs"):
        return ""
    row = db.execute("SELECT blurb FROM community_blurbs WHERE benefit_id = ?", (benefit_id,)).fetchone()
    return row[0] if row else ""
