"""Match explicit issuer statement credits to one unambiguous benefit."""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_STOPWORDS = {
    "access", "annual", "benefit", "card", "chase", "credit", "eligible", "express", "for",
    "membership", "monthly", "offer", "platinum", "preferred", "program", "purchase", "purchases",
    "sapphire", "service", "the", "total", "with",
}


def match_credits(card_id: str, transactions: Iterable[Mapping[str, Any]],
                  benefits: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    benefit_tokens = {row["benefit_id"]: _tokens(str(row["title"])) for row in benefits}
    matches = []
    for transaction in transactions:
        amount = int(transaction["amount_minor"])
        description = str(transaction["description"])
        if "credit" not in description.lower() or not _is_credit(card_id, amount):
            continue
        tokens = _tokens(description)
        scores = {benefit_id: len(tokens & words) for benefit_id, words in benefit_tokens.items()}
        best = max(scores.values(), default=0)
        winners = [benefit_id for benefit_id, score in scores.items() if score == best and score > 0]
        if len(winners) == 1:
            matches.append({"transaction_id": str(transaction["transaction_id"]),
                            "benefit_id": winners[0], "confidence": "explicit"})
    return matches


def _is_credit(card_id: str, amount: int) -> bool:
    return amount < 0 if card_id == "amex_platinum" else amount > 0 if card_id == "chase_sapphire_preferred" else False


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) > 2 and not token.isdigit() and token not in _STOPWORDS}
