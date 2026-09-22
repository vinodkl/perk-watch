"""Parse local CSV/OFX exports and deduplicate stable transaction identities."""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def load_transactions(card_id: str, path: Path, source: str) -> list[dict[str, Any]]:
    rows = _csv(path) if path.suffix.lower() == ".csv" else _ofx(path)
    result = []
    for row in rows:
        posted = _date(row.get("post_date") or row.get("posted_date") or row.get("date") or row.get("transaction_date"))
        description = " ".join(str(row.get("description", "")).split())
        if not posted or not description:
            continue
        amount = _minor(row.get("amount"))
        identity = "|".join((card_id, posted, description.upper(), str(amount), str(row.get("currency", "USD"))))
        result.append({"transaction_id": hashlib.sha256(identity.encode()).hexdigest(), "posted_date": posted,
                       "description": description, "amount_minor": amount, "currency": row.get("currency", "USD"),
                       "merchant": None, "source_id": source})
    return result


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_"): value
                 for key, value in row.items() if key} for row in csv.DictReader(handle)]


def _ofx(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<([A-Z0-9]+)>", r"<\1>", text)
    text = text[text.find("<OFX>"):] if "<OFX>" in text else text
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    result = []
    if root is not None:
        for node in root.iter():
            if node.tag.upper().endswith("STMTTRN"):
                result.append({child.tag.upper().split("}")[-1].replace("DTPOSTED", "date").replace("TRNAMT", "amount").replace("NAME", "description").replace("MEMO", "description"): child.text or "" for child in node})
        if result:
            return result
    # OFX SGML has no closing tags. The small tag parser handles common exports.
    chunks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>)", text, re.S | re.I)
    return [{key.lower(): value.strip() for key, value in re.findall(r"<(DTPOSTED|TRNAMT|NAME|MEMO)>([^<\r\n]+)", chunk, re.I)} for chunk in chunks]


def _date(value: Any) -> str:
    value = str(value).strip()
    compact = re.match(r"(\d{4})(\d{2})(\d{2})", value)
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if compact:
        value = "-".join(compact.groups())
    elif slash:
        value = f"{slash[3]}-{int(slash[1]):02d}-{int(slash[2]):02d}"
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _minor(value: Any) -> int:
    return int((Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100))
