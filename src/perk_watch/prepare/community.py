"""Keep only current, reviewed, conflict-free community ideas and catalog-scoped tips."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


TIPS_FILE = "tips.json"
_TIP_FIELDS = ("source_title", "source_date", "last_verified")
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
        if path.name == TIPS_FILE:
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(document if isinstance(document, list) else document.get("ideas", document.get("served", [])))
    return _filter(rows, benefit_ids, terms_version)


def _load_version(directory: Path, benefit_ids: set[str], terms_version: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates = json.loads((directory / "candidates.json").read_text(encoding="utf-8")).get("candidates", [])
    judgments = {row.get("idea_id"): row for row in json.loads(
        (directory / "model_judgments.json").read_text(encoding="utf-8")).get("judgments", [])}
    source_dates = {}
    results_path = directory / "collection_results.json"
    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        source_dates = {source.get("id"): source.get("source_date", "")
                        for benefit in results.get("benefits", []) for source in benefit.get("sources", [])}
    rows = []
    for candidate in candidates:
        judgment = judgments.get(candidate.get("idea_id"), {})
        rows.append({**candidate, "review_label": judgment.get("review_label"),
                     "terms_version": judgment.get("terms_version", candidate.get("terms_version")),
                     "excerpt": candidate.get("excerpt", candidate.get("source_paraphrase", "")),
                     "source_date": candidate.get("source_date") or source_dates.get(candidate.get("source_id"), "")})
    return _filter(rows, benefit_ids, terms_version)


def _filter(rows: list[dict[str, Any]], benefit_ids: set[str], terms_version: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept, skipped = [], 0
    for row in rows:
        if (row.get("review_label") != "no_known_conflict" or row.get("terms_version") != terms_version
                or row.get("benefit_id") not in benefit_ids or not str(row.get("source_url", "")).startswith("https://")):
            skipped += 1
            continue
        kept.append({key: row.get(key, "") for key in ("idea_id", "benefit_id", "idea", "excerpt", "source_url", "terms_version")}
                    | {"source_date": next((row[key] for key in ("source_date", "posted_at", "created_at", "collection_date") if row.get(key)), "")})
    return kept, {"processed": len(kept), "skipped": skipped}


def tip_id(benefit_id: str, tip: str) -> str:
    return hashlib.sha256(f"{benefit_id}\n{tip}".encode()).hexdigest()[:16]


def load_tips(path: Path, benefit_ids: set[str]) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Read collected tips, keeping only tips for this card's catalog benefits with https sources."""
    if not path.is_file():
        return [], {"processed": 0, "skipped": 0}
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("tips", []) if isinstance(document, dict) else []
    kept: dict[str, dict[str, str]] = {}
    skipped = 0
    for row in rows:
        tip = " ".join(str(row.get("tip", "")).split()) if isinstance(row, dict) else ""
        benefit_id = str(row.get("benefit_id", "")) if isinstance(row, dict) else ""
        url = str(row.get("source_url", "")) if isinstance(row, dict) else ""
        if not tip or benefit_id not in benefit_ids or not url.startswith("https://"):
            skipped += 1
            continue
        key = tip_id(benefit_id, tip)
        if key in kept:
            skipped += 1
            continue
        kept[key] = {"tip_id": key, "benefit_id": benefit_id, "tip": tip, "source_url": url,
                     **{field: str(row.get(field) or "") for field in _TIP_FIELDS}}
    return list(kept.values()), {"processed": len(kept), "skipped": skipped}
