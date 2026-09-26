"""Shared, non-sensitive card catalog for preparation and collection skills."""
from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path


@cache
def load_cards() -> dict[str, dict[str, str]]:
    cards = json.loads(Path(__file__).with_name("cards.json").read_text(encoding="utf-8"))
    if not isinstance(cards, dict) or not cards:
        raise ValueError("card catalog must contain cards")
    for card_id, details in cards.items():
        if (not isinstance(card_id, str) or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", card_id)
                or not isinstance(details, dict) or not isinstance(details.get("display_name"), str)
                or not details["display_name"].strip()
                or details.get("statement_credit_sign") not in {"positive", "negative"}):
            raise ValueError(f"invalid card catalog entry: {card_id}")
    return cards
