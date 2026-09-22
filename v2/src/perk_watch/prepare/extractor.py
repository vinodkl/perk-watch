"""Optional structured benefit extraction through the OpenAI client."""
from __future__ import annotations

import json
from typing import Any


class OpenAIBenefitExtractor:
    def __init__(self, client: Any, model: str = "gpt-4o-mini") -> None:
        self.client, self.model = client, model

    def __call__(self, text: str, source_ref: str) -> list[dict[str, Any]]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "Return JSON {benefits:[...]}. Use null for unclear fields. Every item needs title and supporting terms."},
                      {"role": "user", "content": text}],
        )
        value = json.loads(response.choices[0].message.content)
        return value.get("benefits", []) if isinstance(value, dict) else []
