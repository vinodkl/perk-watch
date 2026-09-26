"""Optional structured benefit extraction through the OpenAI client."""
from __future__ import annotations

import json
from typing import Any

from ..privacy import redact_pii


class OpenAIBenefitExtractor:
    def __init__(self, client: Any, model: str = "gpt-4o-mini") -> None:
        self.client, self.model = client, model

    def __call__(self, text: str, source_ref: str) -> list[dict[str, Any]]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": (
                "Read only the supplied issuer benefit document and return JSON "
                "{benefits:[{benefit_id,title,terms,amount_minor,period,eligible_merchants,"
                "enrollment_required,booking_required}]}. One item per distinct benefit. "
                "amount_minor is whole USD cents, so $100 is 10000. period must be "
                "monthly, quarterly, yearly, account_year, or null. Include only "
                "merchants clearly named as eligible. terms must be a short supporting "
                "excerpt from the supplied document. Extract fields from the title and terms; "
                "use null only when the supplied text does not support the field. "
                "Do not browse, use outside knowledge, or calculate transaction usage. "
                "Preserve any supplied benefit_id and title. Return JSON only."
            )},
                      {"role": "user", "content": f"Source reference: {source_ref}\\n\\n{redact_pii(text)}"}],
        )
        value = json.loads(response.choices[0].message.content)
        return value.get("benefits", []) if isinstance(value, dict) else []
