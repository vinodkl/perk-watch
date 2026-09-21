#!/usr/bin/env python3
"""Resolve local merchant descriptors with OpenAI, without exporting transaction facts.

Only sanitized descriptor text and the fixed local merchant-group vocabulary are
sent. Amounts, dates, identifiers, evidence, filenames, and transaction rows
never leave the local process. Decisions are written only to the local ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from perk_watch.raw_data import data_root

MODEL = os.environ.get("PERKWATCH_MERCHANT_MODEL", "gpt-4o-mini")
PROMPT_VERSION = "vku-27-merchant-groups-v3"
OUTSIDE_GROUPS = "__outside_active_benefit_groups__"
BATCH_SIZE = 40


def sanitize_descriptor(value: str) -> str:
    """Keep merchant words while removing numbers and identifier-like tokens."""
    value = re.sub(r"\b[0-9][A-Za-z0-9._/-]*\b", " ", value)
    value = re.sub(r"[^A-Za-z][^A-Za-z'&. -]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:160]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _groups(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT DISTINCT json_extract(eligibility_json, '$.merchant_group') "
        "FROM active_rules WHERE json_extract(eligibility_json, '$.merchant_group') IS NOT NULL"
    ).fetchall()
    return sorted(row[0] for row in rows)


def _response(client: Any, descriptors: list[str], groups: list[str]) -> list[dict[str, Any]]:
    prompt = {
        "task": "Map each sanitized merchant descriptor to one allowed merchant group, or null if ambiguous.",
        "allowed_groups": groups,
        "descriptors": [{"index": index, "text": text} for index, text in enumerate(descriptors)],
        "rules": [
            "Return JSON only as {decisions:[{index,merchant_group,classification,confidence,reason}]}.",
            "merchant_group must be exactly one allowed group or null.",
            "Use classification outside_groups when the descriptor clearly names a merchant or service that is not one of the allowed groups; use ambiguous only when the text itself is genuinely insufficient.",
            "Use null merchant_group for outside_groups or ambiguous. Never guess an allowed group.",
            "confidence is a number from 0 to 1.",
        ],
    }
    result = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You classify merchant text only. Do not request or infer transaction facts.",
            },
            {"role": "user", "content": json.dumps(prompt, separators=(",", ":"))},
        ],
        response_format={"type": "json_object"},
    )
    value = json.loads(result.choices[0].message.content)
    decisions = value.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("OpenAI response lacks decisions list")
    return decisions


def main() -> None:
    from openai import OpenAI

    root = data_root()
    path = root / "prepared" / "transactions" / "ledger.sqlite3"
    registry_path = root / "prepared" / "rules" / "registry.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        with sqlite3.connect(registry_path) as registry_connection:
            groups = _groups(registry_connection)
        rows = connection.execute(
            "SELECT descriptor FROM merchant_decisions ORDER BY descriptor"
        ).fetchall()
        descriptors = [str(row["descriptor"]) for row in rows]
        sanitized = {descriptor: sanitize_descriptor(descriptor) for descriptor in descriptors}
        inputs = sorted({text for text in sanitized.values() if text})
        client = OpenAI()
        choices: dict[str, dict[str, Any]] = {}
        for start in range(0, len(inputs), BATCH_SIZE):
            batch = inputs[start : start + BATCH_SIZE]
            for item in _response(client, batch, groups):
                index = item.get("index")
                if not isinstance(index, int) or not 0 <= index < len(batch):
                    continue
                choices[batch[index]] = item

        now = datetime.now(timezone.utc).isoformat()
        resolved = indeterminate = 0
        for descriptor in descriptors:
            clean = sanitized[descriptor]
            choice = choices.get(clean, {})
            group = choice.get("merchant_group")
            classification = choice.get("classification")
            confidence = choice.get("confidence")
            confident = isinstance(confidence, (int, float)) and confidence >= 0.75
            if group in groups and confident:
                status = "resolved"
                confidence = float(confidence)
                classification = "matched_group"
                resolved += 1
            elif classification == "outside_groups" and confident:
                group = OUTSIDE_GROUPS
                status = "resolved"
                confidence = float(confidence)
                resolved += 1
            else:
                group = None
                status = "indeterminate"
                indeterminate += 1
            metadata = {
                "method": "openai_merchant_resolution",
                "model": MODEL,
                "prompt_version": PROMPT_VERSION,
                "resolved_at": now,
                "sanitized_descriptor_sha256": _sha256(clean),
                "confidence_threshold": 0.75,
                "candidate_group": choice.get("merchant_group"),
                "classification": classification,
                "model_reason": str(choice.get("reason") or "")[:240],
            }
            connection.execute(
                "UPDATE merchant_decisions SET canonical_merchant=?, resolution_status=?, confidence=?, metadata_json=?, unresolved_reason=? WHERE descriptor=?",
                (group, status, confidence, json.dumps(metadata, sort_keys=True), None if group else "unresolved_merchant", descriptor),
            )
            connection.execute(
                "UPDATE transactions SET canonical_merchant=?, resolution_status=?, unresolved_reason=? WHERE descriptor=?",
                (group, status, None if group else "unresolved_merchant", descriptor),
            )
        connection.commit()

    print(json.dumps({
        "ledger": "local-only",
        "merchant_decision_count": len(descriptors),
        "sanitized_unique_descriptor_count": len(inputs),
        "resolved_count": resolved,
        "indeterminate_count": indeterminate,
        "active_merchant_groups": groups,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
