"""Local-only staging for manually supplied real-world sources."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil


DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "perk-watch"


def data_root() -> Path:
    """Return the configured root without creating it."""
    value = os.environ.get("PERKWATCH_DATA_DIR")
    return Path(value).expanduser() if value else DEFAULT_DATA_DIR


def initialize(root: str | Path | None = None) -> Path:
    """Create the local staging layout and return its root."""
    root = Path(root).expanduser() if root is not None else data_root()
    for relative in (
        "raw/benefits", "raw/transactions", "derived/registry",
        "derived/ledger", "derived/indexes", "manifests",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def import_benefit_guide(
    source: str | Path, *, url: str | None = None,
    terms_version: str | None = None, root: str | Path | None = None,
) -> dict:
    """Copy a manually fetched guide and write an idempotent provenance manifest."""
    return _import(source, "public_benefit_guide", url=url,
                   terms_version=terms_version, root=root, directory="benefits")


def import_transactions(
    source: str | Path, *, root: str | Path | None = None,
) -> dict:
    """Copy a local CSV or OFX export without connecting to an account."""
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".ofx"}:
        raise ValueError("transaction source must be a .csv or .ofx file")
    return _import(source, suffix[1:], root=root, directory="transactions")


def _import(source, source_type, *, url=None, terms_version=None, root=None, directory):
    source = Path(source).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    if url is not None and not url.startswith(("http://", "https://")):
        raise ValueError("guide URL must use http:// or https://")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = initialize(root)
    stored = root / "raw" / directory / f"{digest}{source.suffix.lower()}"
    manifest_path = root / "manifests" / f"{digest}.json"
    if not stored.exists():
        shutil.copyfile(source, stored)
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest = {
        "source_type": source_type,
        "url": url,
        "filename": source.name,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": digest,
        "terms_version": terms_version,
        "stored_path": stored.relative_to(root).as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
