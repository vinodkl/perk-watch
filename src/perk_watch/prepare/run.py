"""Assemble the repeatable, offline V2 monthly preparation."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .benefits import CARDS, load_benefits
from .community import load_ideas
from .credits import match_credits
from .merchants import match_all
from ..search import build_benefit_embeddings, build_community_embeddings
from .storage import connect, replace_card_data
from .transactions import load_transactions


def prepare(root: str | Path, *, extractor: Callable[[str, str], Any] | None = None,
            merchant_chooser: Callable[[tuple[str, ...], tuple[str, ...]], dict[str, str | None]] | None = None,
            embedder: Any | None = None) -> dict[str, Any]:
    root = Path(root).expanduser()
    raw = root / "raw"
    prepared = root / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    db = connect(prepared / "perkwatch.sqlite")
    report: dict[str, Any] = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(), "cards": {}, "unresolved": []}
    try:
        for card_id, display_name in CARDS.items():
            card_dir = raw / card_id.replace("_", "-")
            sources = _sources(card_dir / "sources.json")
            benefit_rows, transactions, ideas, matches, credit_matches = [], [], [], [], []
            counts = Counter()
            benefit_sources = [s for s in sources if s.get("kind") == "benefits"]
            for record in benefit_sources:
                path = root / record["path"]
                try:
                    rows, stats = load_benefits(card_id, path, extractor)
                except (OSError, ValueError, json.JSONDecodeError):
                    counts["skipped"] += 1
                    continue
                benefit_rows.extend(rows)
                counts.update(stats)
            benefit_ids = {row["benefit_id"] for row in benefit_rows}
            terms_version = _terms_version(benefit_rows)
            for record in sources:
                if record.get("kind") != "transactions":
                    continue
                try:
                    transactions.extend(load_transactions(card_id, root / record["path"], record["source_id"]))
                except (OSError, ValueError):
                    counts["skipped"] += 1
            transactions = list({row["transaction_id"]: row for row in transactions}.values())
            merchant_results = match_all((row["description"] for row in transactions), merchant_chooser)
            for row, (merchant, confidence) in zip(transactions, merchant_results):
                row["merchant"] = merchant
                matches.append({"transaction_id": row["transaction_id"], "merchant": merchant, "confidence": confidence})
                if confidence == "unknown":
                    report["unresolved"].append({"kind": "merchant", "transaction_id": row["transaction_id"]})
            credit_matches = match_credits(card_id, transactions, benefit_rows)
            community_dir = card_dir / "community"
            ideas, idea_stats = load_ideas(card_id, community_dir, benefit_ids, terms_version)
            counts.update({"community_processed": idea_stats["processed"], "community_skipped": idea_stats["skipped"],
                           "credit_matches": len(credit_matches), "transactions": len(transactions), "benefits": len(benefit_rows)})
            replace_card_data(db, card_id, display_name, _source_rows(card_id, root, sources), benefit_rows,
                              transactions, matches, credit_matches, ideas)
            if embedder:
                counts["embeddings"] = build_benefit_embeddings(db, embedder, card_id)
                counts["community_embeddings"] = build_community_embeddings(db, embedder, card_id)
            report["cards"][card_id] = dict(sorted(counts.items()))
        db.commit()
    finally:
        db.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["unresolved_count"] = len(report["unresolved"])
    (prepared / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _sources(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for row in document.get("sources", []):
        row = dict(row)
        row["source_id"] = row.get("source_id") or f"{row['card_id']}:{row['kind']}:{row['content_sha256']}"
        result.append(row)
    return result


def _source_rows(card_id: str, root: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_id": row["source_id"], "card_id": card_id, "kind": row["kind"], "path": row["path"], "content_sha256": row["content_sha256"]} for row in sources if (root / row["path"]).exists()]


def _terms_version(rows: list[dict[str, Any]]) -> str:
    value = "\n".join(f"{row['benefit_id']}:{row['terms']}" for row in sorted(rows, key=lambda x: x["benefit_id"]))
    return hashlib.sha256(value.encode()).hexdigest()[:16]
