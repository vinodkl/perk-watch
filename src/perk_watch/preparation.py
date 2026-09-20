"""Build PerkWatch's local data model from card-centered raw inputs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .community import prepare_community
from .benefit_preparation import prepare_benefits
from .raw_data import data_root, initialize, source_records
from .transactions import SQLiteLedger, TransactionSource


def prepare_data(*, root: str | Path | None = None) -> dict[str, Any]:
    """Normalize benefits, transactions, and community notes in one offline run."""
    root = initialize(root or data_root())
    benefits = prepare_benefits(root=root)
    transaction_count = _prepare_transactions(root)
    community = _prepare_community(root)
    report = {
        "schema_version": 1,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "cards": sorted(path.parent.name for path in (root / "raw").glob("*/sources.json")),
        "benefits": {
            "status": benefits["status"],
            "source_count": benefits["source_count"],
            "terms_versions": benefits["terms_versions"],
            "diff_counts": {key: len(value) for key, value in benefits["diff"].items()},
            "invalidations": benefits["invalidations"],
        },
        "transactions": {"count": transaction_count},
        "community": community,
    }
    _write(root / "prepared" / "report.json", report)
    return report


def _prepare_transactions(root: Path) -> int:
    ledger = SQLiteLedger(root)
    seen = set()
    for record in source_records(root):
        if record.get("kind") != "transactions" or record["content_sha256"] in seen:
            continue
        seen.add(record["content_sha256"])
        source = TransactionSource(root / record["path"], card=str(record["card_id"]))
        ledger.ingest(source.load())
    return len(ledger.load_resolved_transactions())


def _prepare_community(root: Path) -> dict[str, Any]:
    current_terms = _read(root / "prepared" / "benefits" / "current.json", {}).get("terms_version")
    results: dict[str, Any] = {}
    for card_root in sorted((root / "raw").iterdir()):
        community_root = card_root / "community"
        if not community_root.is_dir():
            continue
        versions = sorted(path for path in community_root.iterdir() if path.is_dir())
        if not versions:
            continue
        source = versions[-1]
        candidates = _read(source / "candidates.json", {})
        judgments = _read(source / "model_judgments.json", {})
        version = str(candidates.get("corpus_version") or source.name)
        terms_version = str(candidates.get("terms_version") or "")
        if not current_terms or terms_version != current_terms:
            raise ValueError(
                f"{card_root.name} community notes use {terms_version or 'no terms version'}; "
                f"review them against {current_terms or 'the prepared benefit terms'}"
            )
        rows = candidates.get("candidates", [])
        output = root / "prepared" / "community" / card_root.name / version
        manifest = prepare_community(
            rows, judgments.get("judgments", []),
            benefit_ids={str(row["benefit_id"]) for row in rows},
            terms_version=current_terms, output_dir=output, corpus_version=version,
            production_index_dir=root / "prepared" / "indexes" / "community",
        )
        current = output.parent / "current.json"
        _write(current, {"corpus_version": version, "path": output.relative_to(root).as_posix()})
        results[card_root.name] = manifest
    return results


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
