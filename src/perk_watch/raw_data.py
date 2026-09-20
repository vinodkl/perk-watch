"""Store manually collected card data under one card-centered raw layout."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "perk-watch"
KINDS = {"benefits", "transactions"}


def data_root() -> Path:
    """Return the configured local-data root without creating it."""
    value = os.environ.get("PERKWATCH_DATA_DIR")
    return Path(value).expanduser() if value else DEFAULT_DATA_DIR


def initialize(root: str | Path | None = None) -> Path:
    """Create the raw/prepared layout and return its root."""
    root = Path(root).expanduser() if root is not None else data_root()
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "prepared").mkdir(parents=True, exist_ok=True)
    return root


def import_benefit_guide(
    source: str | Path, *, card: str, url: str | None = None,
    effective_from: str | None = None, root: str | Path | None = None,
) -> dict:
    """Store a manually fetched guide below ``raw/<card>/benefits``."""
    if url is not None and not url.startswith(("http://", "https://")):
        raise ValueError("guide URL must use http:// or https://")
    return _import(source, card, "benefits", url=url, effective_from=effective_from, root=root)


def import_transactions(
    source: str | Path, *, card: str, root: str | Path | None = None,
) -> dict:
    """Store a local CSV or OFX export below ``raw/<card>/transactions``."""
    if Path(source).suffix.lower() not in {".csv", ".ofx"}:
        raise ValueError("transaction source must be a .csv or .ofx file")
    return _import(source, card, "transactions", root=root)


def card_directory(card: str) -> str:
    """Return the stable directory slug for a card identifier."""
    value = re.sub(r"[^a-z0-9]+", "-", card.lower()).strip("-")
    if not value:
        raise ValueError("card is required")
    return value


def source_records(root: str | Path | None = None) -> list[dict]:
    """Load every card's raw-source records."""
    root = initialize(root)
    records = []
    for path in sorted((root / "raw").glob("*/sources.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        records.extend(document.get("sources", []))
    return records


def _import(source, card, kind, *, url=None, effective_from=None, root=None):
    source = Path(source).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    if kind not in KINDS:
        raise ValueError(f"unsupported raw-data kind: {kind}")
    root = initialize(root)
    slug = card_directory(card)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    card_root = root / "raw" / slug
    stored = card_root / kind / f"{digest}{source.suffix.lower()}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    if not stored.exists():
        shutil.copyfile(source, stored)

    index_path = card_root / "sources.json"
    document = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {
        "schema_version": 1, "card_id": card, "sources": [],
    }
    record = {
        "card_id": card,
        "kind": kind,
        "filename": source.name,
        "path": stored.relative_to(root).as_posix(),
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": digest,
    }
    if effective_from is not None:
        record["effective_from"] = effective_from
    existing = next((row for row in document["sources"] if row["content_sha256"] == digest), None)
    if existing is not None:
        return existing
    document["sources"].append(record)
    document["sources"].sort(key=lambda row: (row["kind"], row["fetched_at"], row["content_sha256"]))
    index_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record
