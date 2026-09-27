"""Assemble the repeatable, offline V3 preparation.

Usage tracking reads issuer statement-credit lines against catalog.json at runtime, so
preparation only stores the terms library, transactions, community ideas and tips, blurbs,
and search vectors.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from ..cards import load_cards
from ..catalog import load_catalog, match_credit
from ..staging.raw_data import source_id
from .benefits import CARDS, FIELDS, load_benefits
from .blurbs import BlurbWriter, generate_blurbs
from .community import TIPS_FILE, load_ideas, load_tips
from .rag_search_index import build_benefit_embeddings, build_community_embeddings
from .storage import connect, replace_card_data
from .transactions import load_transactions


def prepare(root: str | Path, *, extractor: Callable[[str, str], Any] | None = None,
            embedder: Any | None = None, blurb_writer: BlurbWriter | None = None) -> dict[str, Any]:
    root = Path(root).expanduser()
    raw = root / "raw"
    prepared = root / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    db = connect(prepared / "perkwatch.sqlite")
    catalog = load_catalog()
    report: dict[str, Any] = {"schema_version": 2, "started_at": datetime.now(timezone.utc).isoformat(), "cards": {}, "unresolved": []}
    try:
        for card_id, display_name in CARDS.items():
            card_dir = raw / card_id.replace("_", "-")
            sources = _sources(card_dir / "sources.json")
            catalog_ids = {b.benefit_id for b in catalog if b.card_id == card_id}
            benefit_rows, transactions = [], []
            counts = Counter()
            card_extractor = _reusing_extractor(extractor, _previous_benefits(db, card_id), counts) if extractor else None
            for record in (s for s in sources if s.get("kind") == "benefits"):
                try:
                    rows, stats = load_benefits(card_id, root / record["path"], card_extractor)
                except (OSError, ValueError, json.JSONDecodeError):
                    counts["skipped"] += 1
                    continue
                benefit_rows.extend(rows)
                counts.update(stats)
            benefit_ids = {row["benefit_id"] for row in benefit_rows}
            for record in sources:
                if record.get("kind") != "transactions":
                    continue
                try:
                    transactions.extend(load_transactions(card_id, root / record["path"], record["source_id"]))
                except (OSError, ValueError):
                    counts["skipped"] += 1
            transactions = list({row["transaction_id"]: row for row in transactions}.values())
            community_dir = card_dir / "community"
            ideas, idea_stats = load_ideas(card_id, community_dir, benefit_ids, _terms_version(benefit_rows))
            try:
                tips, tip_stats = load_tips(community_dir / TIPS_FILE, catalog_ids)
            except (OSError, ValueError, json.JSONDecodeError):
                tips, tip_stats = [], {"processed": 0, "skipped": 1}
            counts.update({"community_processed": idea_stats["processed"], "community_skipped": idea_stats["skipped"],
                           "tips_processed": tip_stats["processed"], "tips_skipped": tip_stats["skipped"],
                           "transactions": len(transactions), "benefits": len(benefit_rows),
                           "unmatched_credit_lines": _unmatched_credit_lines(card_id, transactions, catalog)})
            replace_card_data(db, card_id, display_name, _source_rows(card_id, root, sources), benefit_rows,
                              transactions, ideas, tips)
            if embedder:
                counts["embeddings"] = build_benefit_embeddings(db, embedder, card_id)
                counts["community_embeddings"] = build_community_embeddings(db, embedder, card_id)
            card_report: dict[str, Any] = dict(sorted(counts.items()))
            # Catalog credits without a prepared terms row still track, but show no official terms.
            card_report["catalog_missing_terms"] = sorted(catalog_ids - benefit_ids)
            report["cards"][card_id] = card_report
            for benefit_id in card_report["catalog_missing_terms"]:
                report["unresolved"].append({"kind": "catalog_terms", "benefit_id": benefit_id})
        report["blurbs"] = generate_blurbs(db, blurb_writer, catalog)
        db.commit()
    finally:
        db.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["unresolved_count"] = len(report["unresolved"])
    (prepared / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _unmatched_credit_lines(card_id: str, transactions: list[dict[str, Any]], catalog: tuple) -> int:
    """Issuer-credit-signed lines mentioning "credit" that no catalog pattern claims."""
    sign = -1 if load_cards()[card_id]["statement_credit_sign"] == "negative" else 1
    count = 0
    for row in transactions:
        if "credit" not in row["description"].lower() or row["amount_minor"] * sign <= 0:
            continue
        try:
            matched = match_credit(card_id, row["description"], catalog)
        except ValueError:
            matched = None
        count += matched is None
    return count


def _previous_benefits(db: sqlite3.Connection, card_id: str) -> dict[str, dict[str, Any]]:
    columns = ("benefit_id", "terms") + FIELDS
    return {row[0]: dict(zip(columns, row)) for row in db.execute(
        f"SELECT {', '.join(columns)} FROM benefits WHERE card_id = ?", (card_id,))}


def _reusing_extractor(extractor: Callable[[str, str], Any], previous: dict[str, dict[str, Any]],
                       counts: Counter) -> Callable[[str, str], Any]:
    """Reuse fields extracted on an earlier run when a benefit's terms are unchanged.

    Per-benefit extraction requests carry one benefit; if the stored row for that id has the
    same terms, its fields are returned without calling the model, so re-running preparation
    does not re-bill extraction.
    """
    def extract(text: str, source: str) -> Any:
        try:
            items = json.loads(text).get("benefits")
        except (json.JSONDecodeError, AttributeError):
            items = None
        if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict):
            item = items[0]
            old = previous.get(str(item.get("benefit_id")))
            if old and old["terms"] == str(item.get("terms", "")).strip():
                counts["extraction_reused"] += 1
                # mechanism is not a model field; local repair derives it, as on a fresh run.
                fields = {field: old[field] for field in FIELDS if field != "mechanism"}
                for flag in ("enrollment_required", "booking_required"):
                    fields[flag] = None if fields[flag] is None else bool(fields[flag])
                if fields["eligible_merchants"] is not None:
                    fields["eligible_merchants"] = [m for m in str(fields["eligible_merchants"]).split(",") if m]
                return [{**item, **fields}]
        counts["extraction_calls"] += 1
        return extractor(text, source)
    return extract


def _sources(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for row in document.get("sources", []):
        row = dict(row)
        row["source_id"] = row.get("source_id") or source_id(row["card_id"], row["kind"], row["content_sha256"])
        result.append(row)
    return result


def _source_rows(card_id: str, root: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_id": row["source_id"], "card_id": card_id, "kind": row["kind"], "path": row["path"], "content_sha256": row["content_sha256"]} for row in sources if (root / row["path"]).exists()]


def _terms_version(rows: list[dict[str, Any]]) -> str:
    value = "\n".join(f"{row['benefit_id']}:{row['terms']}" for row in sorted(rows, key=lambda x: x["benefit_id"]))
    return hashlib.sha256(value.encode()).hexdigest()[:16]
