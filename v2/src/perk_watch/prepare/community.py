"""Keep only current, reviewed, conflict-free community ideas."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


_VERSION = re.compile(r"community-reddit-(\d{4}-\d{2}-\d{2})\.v(\d+)$")


def load_ideas(card_id: str, directory: Path, benefit_ids: set[str], terms_version: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not directory.is_dir():
        return [], {"processed": 0, "skipped": 0}
    versions = [(match.group(1), int(match.group(2)), path) for path in directory.iterdir()
                if path.is_dir() and (match := _VERSION.fullmatch(path.name))]
    if versions:
        return _load_version(max(versions)[2], benefit_ids, terms_version)

    rows = []
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(document if isinstance(document, list) else document.get("ideas", document.get("served", [])))
    return _filter(rows, benefit_ids, terms_version)


def _load_version(directory: Path, benefit_ids: set[str], terms_version: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates = json.loads((directory / "candidates.json").read_text(encoding="utf-8")).get("candidates", [])
    judgments = {row.get("idea_id"): row for row in json.loads(
        (directory / "model_judgments.json").read_text(encoding="utf-8")).get("judgments", [])}
    rows = []
    for candidate in candidates:
        judgment = judgments.get(candidate.get("idea_id"), {})
        rows.append({**candidate, "review_label": judgment.get("review_label"),
                     "terms_version": judgment.get("terms_version", candidate.get("terms_version")),
                     "excerpt": candidate.get("excerpt", candidate.get("source_paraphrase", ""))})
    return _filter(rows, benefit_ids, terms_version)


def _filter(rows: list[dict[str, Any]], benefit_ids: set[str], terms_version: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept, skipped = [], 0
    for row in rows:
        if (row.get("review_label") != "no_known_conflict" or row.get("terms_version") != terms_version
                or row.get("benefit_id") not in benefit_ids or not str(row.get("source_url", "")).startswith("https://")):
            skipped += 1
            continue
        kept.append({key: row.get(key, "") for key in ("idea_id", "benefit_id", "idea", "excerpt", "source_url", "terms_version")})
    return kept, {"processed": len(kept), "skipped": skipped}
