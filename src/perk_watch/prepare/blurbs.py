"""One- or two-sentence community blurbs per catalog benefit, cached by the tips they summarize."""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Callable

from ..catalog import CatalogBenefit, load_catalog

# A writer turns the prompt into blurb text. It may carry a `model` attribute for bookkeeping.
BlurbWriter = Callable[[str], str]
MODEL = "gpt-4o-mini"


def blurb_prompt(tips: list[str]) -> str:
    return ("In at most 2 short sentences, summarize what cardholders do with this benefit, "
            "based only on these tips. Start with 'People'. No links.\n" +
            "\n".join(f"- {tip}" for tip in tips))


def tips_sha256(tips: list[str]) -> str:
    return hashlib.sha256("\n".join(tips).encode()).hexdigest()


def _tips(db: sqlite3.Connection, benefit_id: str) -> list[str]:
    """Collected tips then reviewed V2 community ideas, in the order the runtime shows them."""
    tips = [row[0] for row in db.execute(
        "SELECT tip FROM community_tips WHERE benefit_id = ? ORDER BY tip_id", (benefit_id,))]
    tips += [row[0] for row in db.execute(
        "SELECT idea FROM community_ideas WHERE benefit_id = ? ORDER BY idea_id", (benefit_id,))]
    return tips


def generate_blurbs(db: sqlite3.Connection, writer: BlurbWriter | None,
                    catalog: tuple[CatalogBenefit, ...] | None = None) -> dict[str, Any]:
    """Write a blurb for every catalog benefit with tips; reuse one whose tips are unchanged.

    A blurb whose tips changed (or vanished) is removed when it cannot be rewritten, so a
    stored blurb only ever summarizes the tips currently stored beside it.
    """
    stats: dict[str, Any] = {"written": 0, "cached": 0, "removed": 0, "pending": 0}
    model = str(getattr(writer, "model", "custom")) if writer else ""
    existing = {benefit_id: digest for benefit_id, digest in
                db.execute("SELECT benefit_id, tips_sha256 FROM community_blurbs")}
    wanted = set()
    for benefit in catalog or load_catalog():
        tips = _tips(db, benefit.benefit_id)
        if not tips:
            continue
        wanted.add(benefit.benefit_id)
        digest = tips_sha256(tips)
        if existing.get(benefit.benefit_id) == digest:
            stats["cached"] += 1
            continue
        if writer is None:
            stats["pending"] += 1
            if benefit.benefit_id in existing:
                db.execute("DELETE FROM community_blurbs WHERE benefit_id = ?", (benefit.benefit_id,))
                stats["removed"] += 1
            continue
        text = " ".join(str(writer(blurb_prompt(tips)) or "").split())
        if not text:
            stats["pending"] += 1
            db.execute("DELETE FROM community_blurbs WHERE benefit_id = ?", (benefit.benefit_id,))
            continue
        db.execute("INSERT OR REPLACE INTO community_blurbs VALUES (?, ?, ?, ?)",
                   (benefit.benefit_id, text, model, digest))
        stats["written"] += 1
    for benefit_id in set(existing) - wanted:
        db.execute("DELETE FROM community_blurbs WHERE benefit_id = ?", (benefit_id,))
        stats["removed"] += 1
    if writer is None and stats["pending"]:
        stats["note"] = "blurbs skipped: no writer (set OPENAI_API_KEY)"
    return stats


class OpenAIBlurbWriter:
    def __init__(self, client: Any, model: str = MODEL) -> None:
        self.client, self.model = client, model

    def __call__(self, prompt: str) -> str:
        response = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}])
        return (response.choices[0].message.content or "").strip()


def default_writer(model: str = MODEL) -> OpenAIBlurbWriter | None:
    """The OpenAI writer when a key is configured, else None (blurbs are then skipped)."""
    from ..embeddings import _api_key
    key = _api_key()
    if not key:
        return None
    from openai import OpenAI
    return OpenAIBlurbWriter(OpenAI(api_key=key), model)
