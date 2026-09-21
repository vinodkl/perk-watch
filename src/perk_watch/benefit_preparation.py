"""Prepare manually collected issuer benefit guides."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .raw_data import data_root, initialize, source_records

EXTRACTION_VERSION = 3


def prepare_benefits(*, root: str | Path | None = None, effective_from: str | None = None) -> dict[str, Any]:
    """Hash raw guides, diff clause chunks, and write the prepared benefit model."""
    root = initialize(root or data_root())
    current_path = root / "prepared" / "benefits" / "current.json"
    previous = _read(current_path, {"sources": {}, "clauses": []})
    sources = _latest_guides(root)
    clauses: list[dict[str, Any]] = []
    source_state: dict[str, dict[str, Any]] = {}
    changed_source_ids: set[str] = set()

    for source_id, manifest in sorted(sources.items()):
        raw_path = root / manifest["path"]
        digest = _sha256(raw_path)
        old_source = previous.get("sources", {}).get(source_id, {})
        old_clauses = [row for row in previous.get("clauses", []) if row.get("source_id") == source_id]
        if (old_source.get("content_sha256") == digest
                and old_source.get("extraction_version") == EXTRACTION_VERSION
                and old_clauses):
            source_version = old_source["terms_version"]
            new_clauses = old_clauses
        else:
            changed_source_ids.add(source_id)
            source_version = f"terms-{digest[:16]}"
            new_clauses = _extract(raw_path, source_id, manifest, source_version, effective_from)
        clauses.extend(new_clauses)
        source_state[source_id] = {
            "source_id": source_id,
            "card_id": manifest.get("card_id"),
            "filename": manifest.get("filename"),
            "url": manifest.get("url"),
            "content_sha256": digest,
            "terms_version": source_version,
            "effective_from": manifest.get("effective_from", effective_from),
            "clause_count": len(new_clauses),
            "extraction_version": EXTRACTION_VERSION,
            "clause_ids": [row["clause_id"] for row in new_clauses],
        }

    old_by_id = {row["clause_id"]: row for row in previous.get("clauses", [])}
    new_by_id = {row["clause_id"]: row for row in clauses}
    diff = {
        "added": [new_by_id[key] for key in sorted(set(new_by_id) - set(old_by_id))],
        "removed": [old_by_id[key] for key in sorted(set(old_by_id) - set(new_by_id))],
        "changed": [
            {"before": old_by_id[key], "after": new_by_id[key]}
            for key in sorted(set(old_by_id) & set(new_by_id))
            if _comparable(old_by_id[key]) != _comparable(new_by_id[key])
        ],
    }
    changed = diff["added"] + diff["removed"] + [item["after"] for item in diff["changed"]]
    changed_benefits = {row["benefit_id"] for row in changed if row.get("benefit_id")}
    old_versions = {row.get("terms_version") for row in diff["removed"]}
    old_versions.update(item["before"].get("terms_version") for item in diff["changed"])
    invalidations = _find_invalidations(root, changed_source_ids, changed_benefits, old_versions)

    no_op = not any(diff.values()) and bool(previous.get("clauses"))
    if no_op:
        corpus = previous
    else:
        corpus = {
            "schema_version": 1,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "sources": source_state,
            "clauses": sorted(clauses, key=lambda row: row["clause_id"]),
        }
        corpus["terms_version"] = _corpus_version(corpus)
        current_path.parent.mkdir(parents=True, exist_ok=True)
        _write(current_path, corpus)
        version_dir = current_path.parent / corpus["terms_version"]
        version_dir.mkdir(parents=True, exist_ok=True)
        _write(version_dir / "clauses.json", corpus)
        _update_source_records(root, source_state, corpus["prepared_at"])

    report = {
        "schema_version": 1,
        "status": "no_change" if no_op else "updated",
        "source_count": len(source_state),
        "terms_versions": {key: value["terms_version"] for key, value in sorted(source_state.items())},
        "diff": diff,
        "invalidations": invalidations,
    }
    report_dir = root / "prepared"
    report_dir.mkdir(parents=True, exist_ok=True)
    _write(report_dir / "report.json", report)
    return report


def _latest_guides(root: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in source_records(root):
        if record.get("kind") != "benefits" or not record.get("path"):
            continue
        identity = record.get("url") or record.get("filename") or record["content_sha256"]
        source_id = f"{record['card_id']}:{identity}"
        old = latest.get(source_id)
        if old is None or str(record.get("fetched_at", "")) > str(old.get("fetched_at", "")):
            latest[source_id] = record
    return latest


def _extract(path: Path, source_id: str, manifest: Mapping[str, Any], terms_version: str, default_effective: str | None) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("PDF preparation requires the pdfplumber dependency") from exc
        with pdfplumber.open(path) as pdf:
            paragraphs = [(page.page_number, text) for page in pdf.pages for text in _paragraphs(page.extract_text() or "")]
        chunks = [(f"chunk-{page:03d}-{index:03d}", text, None) for index, (page, text) in enumerate(paragraphs, 1)]
    elif path.suffix.lower() == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
        chunks = []
        for item in document.get("benefits", []):
            title = str(item.get("title") or item.get("source_label") or "benefit")
            benefit_id = item.get("benefit_id")
            for index, text in enumerate(_paragraphs(str(item.get("text", ""))), 1):
                chunks.append((f"{_slug(title)}-{index:03d}", text, benefit_id))
    else:
        text = path.read_text(encoding="utf-8")
        chunks = _line_benefits(text, source_id) if source_id.startswith("chase_sapphire_preferred:") else [
            (f"chunk-{index:03d}", paragraph, None)
            for index, paragraph in enumerate(_paragraphs(text), 1)
        ]
    effective = manifest.get("effective_from", default_effective)
    digest = _sha256(path)
    return [{
        "clause_id": f"{source_id}:{key}", "source_id": source_id, "benefit_id": benefit_id,
        "terms_version": terms_version, "effective_from": effective, "effective_to": None,
        "text": text, "source_ref": source_id, "source_sha256": digest,
    } for key, text, benefit_id in chunks]


def _line_benefits(text: str, source_id: str) -> list[tuple[str, str, str | None]]:
    """Split a captured card-benefit page into title-level clauses."""
    ignored = {
        "Featured benefits", "Maximize your credits", "Enjoy membership perks",
        "Get more with your card", "Be protected and insured", "Travel", "Dining",
        "Rewards", "Shopping", "Protection", "Service", "All benefits", "Track usage",
        "Select a filter", "Transfer points",
    }
    rows = []
    started = False
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line == "Featured benefits":
            started = True
            continue
        if not started or not line or line in ignored:
            continue
        if line in {"Activated", "Activation required"} or line.startswith(("For details", "*For details")):
            continue
        if re.fullmatch(r"\$?\d[\d,.]*(?:x)?", line) or line.startswith(("Max value", "Annual value", "Every ")):
            continue
        if line.startswith("Please see your Rewards"):
            break
        if line.startswith(("Sign out", "Skip ", "Accounts", "Pay & transfer", "Plan & track",
                            "Investments", "Benefits & travel", "Security & privacy", "Explore products",
                            "Sapphire Preferred")):
            continue
        slug = _slug(line.rstrip("*"))
        rows.append((f"{slug}-001", line, None))
    return rows


def _find_invalidations(root: Path, source_ids: set[str], benefit_ids: set[str], old_versions: set[str | None]) -> dict[str, list[dict[str, str]]]:
    roots = {
        "active_rules": root / "prepared" / "rules",
        "cached_or_indexed_artifacts": root / "prepared" / "indexes",
        "prior_conclusions": root / "prepared" / "conclusions",
        "citations": root / "prepared" / "citations",
        "frozen_evaluation_cases": Path(__file__).resolve().parents[2] / "evals" / "data" / "frozen" / "eval",
    }
    result = {name: [] for name in roots}
    needles = source_ids | benefit_ids | {value for value in old_versions if value}
    for kind, directory in roots.items():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".txt", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(needle in text for needle in needles):
                result[kind].append({"path": path.as_posix(), "reason": "references changed guide terms"})
            elif source_ids and kind in {"active_rules", "cached_or_indexed_artifacts", "prior_conclusions", "citations"}:
                result[kind].append({"path": path.as_posix(), "reason": "guide changed; linkage requires review"})
    return result


def _update_source_records(root: Path, states: Mapping[str, Mapping[str, Any]], prepared_at: str) -> None:
    for path in sorted((root / "raw").glob("*/sources.json")):
        document = _read(path, {})
        for record in document.get("sources", []):
            identity = record.get("url") or record.get("filename") or record.get("content_sha256")
            source_id = f"{record.get('card_id')}:{identity}"
            if source_id not in states:
                continue
            state = states[source_id]
            record["terms_version"] = state["terms_version"]
            record["extraction"] = {
                "clause_count": state["clause_count"],
                "clause_ids": state["clause_ids"],
                "prepared_at": prepared_at,
            }
        _write(path, document)


def _paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "benefit"


def _comparable(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("text", "effective_from", "effective_to", "benefit_id"))


def _corpus_version(corpus: Mapping[str, Any]) -> str:
    sources = corpus.get("sources", {})
    value = json.dumps({key: row["content_sha256"] for key, row in sources.items()}, sort_keys=True).encode()
    return "terms-" + hashlib.sha256(value).hexdigest()[:16]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
