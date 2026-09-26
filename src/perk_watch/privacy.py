"""Redact high-confidence personal data from outbound model requests."""
from __future__ import annotations

import re

_PATTERNS = (
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    (re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b"), "<SSN>"),
    (re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "<CARD_NUMBER>"),
    (re.compile(r"(?<!\d)(?:\+?\d[ -.]?){10,15}(?!\d)"), "<PHONE>"),
    (re.compile(r"https?://[^\s]+", re.I), "<URL>"),
    (re.compile(r"\b\d+\s+[A-Za-z][A-Za-z .'-]{1,40}\s+"
                r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b", re.I), "<ADDRESS>"),
)


def redact_pii(text: str) -> str:
    """Redact high-confidence PII while preserving benefit terms and amounts."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
