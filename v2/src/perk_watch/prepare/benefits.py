"""Load and validate benefit guides, with an injectable LLM boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

CARDS = {
    "amex_platinum": "Amex Platinum",
    "chase_sapphire_preferred": "Chase Sapphire Preferred",
}
FIELDS = ("amount_minor", "period", "eligible_merchants", "enrollment_required", "booking_required")


def source_id(card_id: str, path: Path) -> str:
    return f"{card_id}:benefits:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def load_benefits(card_id: str, path: Path, extractor: Callable[[str, str], Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    source = source_id(card_id, path)
    raw = _structured_document(text)
    if raw is None:
        raw = extractor(text, source) if extractor else _local_document(text)
    if not isinstance(raw, list):
        raise ValueError("benefit extractor must return a list")
    result = []
    skipped = 0
    for index, item in enumerate(raw, 1):
        try:
            row = _validate(item, card_id, source, index)
        except (TypeError, ValueError, KeyError):
            skipped += 1
            continue
        result.append(row)
    return result, {"processed": len(result), "skipped": skipped, "unresolved": sum(_unknown(row) for row in result)}


def _structured_document(text: str) -> list[Mapping[str, Any]] | None:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(document, list):
        return document
    benefits = document.get("benefits") if isinstance(document, dict) else None
    return benefits if isinstance(benefits, list) else None


def _local_document(text: str) -> list[Mapping[str, Any]]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return [{"title": line.strip(), "terms": line.strip()} for line in text.splitlines() if line.strip()]
    return document.get("benefits", document) if isinstance(document, dict) else document


def _validate(item: Mapping[str, Any], card_id: str, source: str, index: int) -> dict[str, Any]:
    if not isinstance(item, Mapping) or not str(item.get("title", "")).strip():
        raise ValueError("benefit title is required")
    benefit_id = str(item.get("benefit_id") or f"{card_id}_benefit_{index:03d}")
    if not benefit_id.startswith(card_id + "_"):
        raise ValueError("benefit id must be stable within its card")
    row = {"benefit_id": benefit_id, "title": str(item["title"]).strip(), "terms": str(item.get("terms", "")).strip(), "source_id": source}
    if not row["terms"]:
        raise ValueError("supporting benefit text is required")
    for field in FIELDS:
        value = item.get(field)
        if field == "amount_minor" and value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError("amount_minor must be a non-negative integer or unknown")
        if field in {"enrollment_required", "booking_required"} and value is not None and not isinstance(value, bool):
            raise ValueError(f"{field} must be boolean or unknown")
        row[field] = value
    row["eligible_merchants"] = ",".join(map(str, item.get("eligible_merchants", []))) if isinstance(item.get("eligible_merchants", []), list) else item.get("eligible_merchants")
    return row


def _unknown(row: Mapping[str, Any]) -> int:
    return sum(row.get(field) is None for field in FIELDS)
