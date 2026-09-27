"""Hand-checked catalog of trackable credits and their statement-credit patterns."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from .cards import load_cards

PERIODS = ("monthly", "quarterly", "semiannual", "annual")
TRACKING = ("auto", "manual")


@dataclass(frozen=True)
class CatalogBenefit:
    # benefit_id matches the prepared `benefits` row, which supplies the official terms text.
    benefit_id: str
    card_id: str
    title: str
    category: str
    period: str
    amount_minor: int
    tracking: str
    credit_pattern: str = ""
    pattern_verified: bool = False
    enrollment_required: bool = False
    overrides: dict[int, int] = field(default_factory=dict)

    def amount_for(self, period_start_month: int) -> int:
        return self.overrides.get(period_start_month, self.amount_minor)


@cache
def load_catalog(path: str | None = None) -> tuple[CatalogBenefit, ...]:
    source = Path(path) if path else Path(__file__).with_name("catalog.json")
    document = json.loads(source.read_text(encoding="utf-8"))
    cards = load_cards()
    benefits, seen = [], set()
    for row in document["benefits"]:
        benefit = CatalogBenefit(**{**row, "overrides": {int(k): int(v) for k, v in row.get("overrides", {}).items()}})
        if benefit.benefit_id in seen:
            raise ValueError(f"duplicate catalog benefit: {benefit.benefit_id}")
        if benefit.card_id not in cards or benefit.period not in PERIODS or benefit.tracking not in TRACKING:
            raise ValueError(f"invalid catalog benefit: {benefit.benefit_id}")
        if benefit.amount_minor <= 0 or any(v <= 0 or not 1 <= k <= 12 for k, v in benefit.overrides.items()):
            raise ValueError(f"invalid catalog amount: {benefit.benefit_id}")
        if (benefit.tracking == "auto") != bool(benefit.credit_pattern):
            raise ValueError(f"auto tracking needs a credit_pattern, manual must not have one: {benefit.benefit_id}")
        if benefit.credit_pattern:
            re.compile(benefit.credit_pattern)
        seen.add(benefit.benefit_id)
        benefits.append(benefit)
    return tuple(benefits)


def catalog_by_id() -> dict[str, CatalogBenefit]:
    return {benefit.benefit_id: benefit for benefit in load_catalog()}


def match_credit(card_id: str, description: str, catalog: tuple[CatalogBenefit, ...] | None = None) -> str | None:
    """Return the one benefit whose credit_pattern matches this statement line.

    More than one match is a catalog error, not something to guess at.
    """
    hits = [b.benefit_id for b in (catalog or load_catalog())
            if b.card_id == card_id and b.credit_pattern and re.search(b.credit_pattern, description, re.I)]
    if len(hits) > 1:
        raise ValueError(f"statement line matches several benefits: {hits}")
    return hits[0] if hits else None
