"""Offline snapshot builder for manually collected public-community metadata."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

LABELS = {"explicit_conflict", "no_known_conflict", "unclear"}
FORBIDDEN_FIELDS = {"author", "username", "body", "comment_body", "thread", "title"}


def freeze_snapshot(candidates: Iterable[Mapping[str, object]], judgments: Iterable[Mapping[str, object]], *,
                    benefit_ids: Iterable[str], terms_version: str, output_dir: str | Path,
                    corpus_version: str, production_index_dir: str | Path) -> dict[str, object]:
    """Freeze reviewed public metadata; network collection happens before this call."""
    output_dir = Path(output_dir)
    if output_dir.resolve() == Path(production_index_dir).resolve():
        raise ValueError("snapshot output must not be the production community index")
    expected_benefits = set(benefit_ids)
    rows = _deduplicate(candidates)
    if not {str(row["benefit_id"]) for row in rows} <= expected_benefits:
        raise ValueError("candidate references an unknown benefit")
    by_idea = {str(row["idea_id"]): row for row in judgments}
    reviewed = []
    for row in rows:
        judgment = by_idea.get(str(row["idea_id"]))
        if not judgment or judgment.get("terms_version") != terms_version:
            raise ValueError(f"missing current-terms model judgment: {row['idea_id']}")
        label = str(judgment.get("label"))
        if label not in LABELS or judgment.get("review_method") != "model_only":
            raise ValueError(f"invalid model judgment: {row['idea_id']}")
        reviewed.append(row | {"review_label": label, "terms_version": terms_version,
                               "corpus_version": corpus_version})
    served = [row | {"served": True} for row in reviewed if row["review_label"] == "no_known_conflict"]
    conflicts = [row | {"served": False} for row in reviewed if row["review_label"] == "explicit_conflict"]
    if any(sum(row["benefit_id"] == benefit for row in served) > 8 for benefit in expected_benefits):
        raise ValueError("served ideas exceed eight per benefit")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write(output_dir / "served_ideas.json", _collection(corpus_version, terms_version, served))
    _write(output_dir / "conflicting_ideas.json", _collection(corpus_version, terms_version, conflicts, never_served=True))
    manifest = {"corpus_version": corpus_version, "terms_version": terms_version,
                "candidate_counts": dict(sorted(Counter(row["benefit_id"] for row in rows).items())),
                "review_counts": dict(sorted(Counter(row["review_label"] for row in reviewed).items())),
                "model_review_only": True, "network_accessed": False,
                "production_index_modified": False}
    _write(output_dir / "manifest.json", manifest)
    return manifest


def stale_idea_ids(ideas: Iterable[Mapping[str, object]], current_terms_version: str) -> tuple[str, ...]:
    return tuple(sorted(str(row["idea_id"]) for row in ideas if row.get("terms_version") != current_terms_version))


def _deduplicate(candidates: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    required = {"idea_id", "benefit_id", "source_kind", "source_id", "source_url", "source_date", "fetched_at", "excerpt", "idea", "source_origin"}
    unique = {}
    for value in candidates:
        if not required <= value.keys() or FORBIDDEN_FIELDS & value.keys():
            raise ValueError("candidate must contain only allowed public metadata and paraphrases")
        if value["source_origin"] != "public_reddit" or not str(value["source_url"]).startswith("https://www.reddit.com/"):
            raise ValueError("candidate must be a public Reddit source")
        key = (str(value["benefit_id"]), str(value["source_kind"]), str(value["source_id"]))
        unique.setdefault(key, dict(value))
    return sorted(unique.values(), key=lambda row: str(row["idea_id"]))


def _collection(version: str, terms_version: str, ideas: list[dict[str, object]], never_served: bool = False) -> dict[str, object]:
    result = {"corpus_version": version, "terms_version": terms_version, "ideas": ideas}
    if never_served:
        result["purpose"] = "Authority-boundary safety cases only; never served or indexed."
    return result


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
