"""Load and validate benefit guides, with an injectable LLM boundary."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from ..staging.raw_data import source_id

CARDS = {
    "amex_platinum": "Amex Platinum",
    "chase_sapphire_preferred": "Chase Sapphire Preferred",
}
FIELDS = ("amount_minor", "period", "eligible_merchants", "enrollment_required", "booking_required")
PERIODS = {"monthly", "quarterly", "yearly", "account_year"}


def load_benefits(card_id: str, path: Path, extractor: Callable[[str, str], Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    source = source_id(card_id, "benefits", hashlib.sha256(path.read_bytes()).hexdigest())
    structured = _json_items(text)
    raw = _structured_document(text)
    if raw is None:
        if extractor and structured:
            extracted = []
            for item in structured:
                evidence = {key: value for key, value in item.items() if value is not None}
                result = extractor(json.dumps({"benefits": [evidence]}), source)
                if isinstance(result, list):
                    extracted.extend(result)
        else:
            extracted = extractor(text, source) if extractor else _local_document(text)
        raw = _merge_structured(structured, extracted) if structured else extracted
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


def _json_items(text: str) -> list[Mapping[str, Any]]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return []
    benefits = document if isinstance(document, list) else document.get("benefits") if isinstance(document, dict) else None
    return benefits if isinstance(benefits, list) and all(isinstance(item, Mapping) for item in benefits) else []


def _structured_document(text: str) -> list[Mapping[str, Any]] | None:
    benefits = _json_items(text)
    required = {"amount_minor", "period", "eligible_merchants"}
    return benefits if benefits and all(required <= item.keys() and all(item[field] is not None for field in required)
                                        for item in benefits) else None


def _merge_structured(original: list[Mapping[str, Any]], extracted: Any) -> list[Mapping[str, Any]]:
    if not isinstance(extracted, list):
        return original
    extracted = [item for item in extracted if isinstance(item, Mapping)]
    by_id = {str(item.get("benefit_id")): item for item in extracted if item.get("benefit_id")}
    by_title = {str(item.get("title", "")).strip().lower(): item for item in extracted}
    merged = []
    fields = set(FIELDS)
    for index, item in enumerate(original):
        match = by_id.get(str(item.get("benefit_id"))) or by_title.get(str(item.get("title", "")).strip().lower())
        if match is None and len(extracted) == len(original):
            match = extracted[index]
        row = dict(item)
        if match:
            row.update({key: value for key, value in match.items() if key in fields and value is not None})
        merged.append(row)
    return merged


def _local_document(text: str) -> list[Mapping[str, Any]]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return [{"title": line.strip(), "terms": line.strip()} for line in text.splitlines() if line.strip()]
    return document.get("benefits", document) if isinstance(document, dict) else document


def _repair_obvious_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(item)
    text = f"{item.get('title', '')} {item.get('terms', '')}"
    if item.get("period") is None:
        match = re.search(r"\b(monthly|each month|per month|quarterly|each quarter|per quarter|annual|annually|yearly|calendar year)\b", text, re.I)
        if match:
            word = match.group(1).lower()
            item["period"] = "monthly" if "month" in word else "quarterly" if "quarter" in word else "yearly"
    if item.get("amount_minor") is None:
        match = re.search(r"\b(?:up to|credit of|credit for|reimbursement of|reimburse(?:ment)? up to|benefit of)\s*\$\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
        if match:
            item["amount_minor"] = int(Decimal(match.group(1).replace(",", "")) * 100)
    return item


def _validate(item: Mapping[str, Any], card_id: str, source: str, index: int) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ValueError("benefit must be an object")
    item = _repair_obvious_fields(item)
    if not str(item.get("title", "")).strip():
        raise ValueError("benefit title is required")
    benefit_id = str(item.get("benefit_id") or f"{card_id}_benefit_{index:03d}")
    if not benefit_id.startswith(card_id + "_"):
        raise ValueError("benefit id must be stable within its card")
    row = {"benefit_id": benefit_id, "title": str(item["title"]).strip(), "terms": str(item.get("terms", "")).strip(), "source_id": source}
    if not row["terms"]:
        raise ValueError("supporting benefit text is required")
    for field in FIELDS:
        value = item.get(field)
        if field == "amount_minor" and value is not None:
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if not isinstance(value, int) or value < 0:
                value = None
        if field == "period" and value is not None:
            period = str(value).strip().lower().replace("-", "_").replace(" ", "_")
            value = {"annual": "yearly", "year": "yearly", "month": "monthly", "quarter": "quarterly"}.get(period, period)
            if value not in PERIODS:
                value = None
        if field in {"enrollment_required", "booking_required"} and value is not None and not isinstance(value, bool):
            value = None
        row[field] = value
    merchants = item.get("eligible_merchants", [])
    if isinstance(merchants, str):
        merchants = merchants.split(",")
    if merchants is not None and not isinstance(merchants, list):
        merchants = None
    row["eligible_merchants"] = ",".join(str(value).strip() for value in merchants if str(value).strip()) if merchants is not None else None
    return row


def _unknown(row: Mapping[str, Any]) -> int:
    return sum(row.get(field) is None for field in FIELDS)
