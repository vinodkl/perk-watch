"""Local merchant matching with a privacy-safe batched model fallback."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable, Mapping, Optional

from ..privacy import redact_pii

MERCHANTS = ("airbnb", "doordash", "global entry", "lululemon", "nytimes", "uber", "whole foods")
BatchChooser = Callable[[tuple[str, ...], tuple[str, ...]], Mapping[str, Optional[str]]]


def match_all(descriptions: Iterable[str], chooser: BatchChooser | None = None) -> list[tuple[str | None, str]]:
    cleaned = [_clean(description) for description in descriptions]
    result: list[tuple[str | None, str] | None] = [None] * len(cleaned)
    unknown: dict[str, list[int]] = {}
    for index, value in enumerate(cleaned):
        merchant = next((candidate for candidate in MERCHANTS if candidate in value), None)
        if merchant:
            result[index] = (merchant, "exact")
            continue
        safe = _model_safe(value)
        if safe:
            unknown.setdefault(safe, []).append(index)
        else:
            result[index] = (None, "unknown")
    choices = chooser(tuple(unknown), MERCHANTS) if chooser and unknown else {}
    for description, indexes in unknown.items():
        merchant = choices.get(description)
        match = (merchant, "model") if merchant in MERCHANTS else (None, "unknown")
        for index in indexes:
            result[index] = match
    return [value or (None, "unknown") for value in result]


class OpenAIMerchantChooser:
    def __init__(self, client: Any, model: str = "gpt-4o-mini", batch_size: int = 100) -> None:
        self.client, self.model, self.batch_size = client, model, batch_size

    def __call__(self, descriptions: tuple[str, ...], merchants: tuple[str, ...]) -> dict[str, str | None]:
        result = {description: None for description in descriptions}
        for start in range(0, len(descriptions), self.batch_size):
            batch = descriptions[start:start + self.batch_size]
            outbound = tuple(redact_pii(description) for description in batch)
            outbound_to_original = dict(zip(outbound, batch))
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Match each cleaned transaction merchant description to exactly one supplied merchant, or null. Return JSON {matches:[{description,merchant}]}. Never invent a merchant."},
                    {"role": "user", "content": json.dumps({"descriptions": outbound, "merchants": merchants})},
                ],
            )
            try:
                rows = json.loads(response.choices[0].message.content).get("matches", [])
            except (AttributeError, json.JSONDecodeError, TypeError):
                rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                description, merchant = row.get("description"), row.get("merchant")
                original = outbound_to_original.get(description)
                if original in result and merchant in merchants:
                    result[original] = merchant
        return result


def _clean(description: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", description.lower()).split())


def _model_safe(description: str) -> str:
    return " ".join(re.sub(r"\b\w*\d\w*\b", " ", description).split())
