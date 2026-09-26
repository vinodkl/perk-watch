"""Register user-supplied local files for offline preparation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..cards import load_cards

def source_id(card: str, kind: str, digest: str) -> str:
    return f"{card}:{kind}:{digest}"


def _import(path: str | Path, card: str, kind: str, *, url: str | None = None,
            root: str | Path | None = None) -> dict:
    if card not in load_cards():
        raise ValueError("unsupported card ID")
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("source must be a file")
    allowed = {"benefits": {".json", ".txt"}, "transactions": {".csv", ".ofx"}}
    if source.suffix.lower() not in allowed[kind]:
        raise ValueError(f"unsupported {kind} file format: {source.suffix}")
    data_root = Path(root or os.environ.get("PERKWATCH_DATA_DIR", "data/real")).expanduser().resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = data_root / "raw" / card.replace("_", "-") / kind / f"{digest}{source.suffix.lower()}"
    index = destination.parent.parent / "sources.json"
    document = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {
        "schema_version": 1, "card_id": card, "sources": []}
    identity = source_id(card, kind, digest)
    existing = next((row for row in document["sources"] if row.get("kind") == kind
                     and row.get("content_sha256") == digest), None)
    if existing:
        registered = data_root / existing["path"]
        if not registered.is_file() or hashlib.sha256(registered.read_bytes()).hexdigest() != digest:
            raise ValueError("registered source is missing or changed")
        return existing
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source != destination:
        shutil.copyfile(source, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError("source changed during import")
    row = {"card_id": card, "kind": kind, "filename": destination.name,
           "path": destination.relative_to(data_root).as_posix(), "content_sha256": digest,
           "source_id": identity, "fetched_at": datetime.now(timezone.utc).isoformat()}
    if url:
        row["url"] = url
    document["sources"].append(row)
    index.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return row


def import_benefit_guide(path: str | Path, *, card: str, url: str | None = None,
                         root: str | Path | None = None) -> dict:
    return _import(path, card, "benefits", url=url, root=root)


def import_transactions(path: str | Path, *, card: str, root: str | Path | None = None) -> dict:
    return _import(path, card, "transactions", root=root)
