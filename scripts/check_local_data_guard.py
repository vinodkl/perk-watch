#!/usr/bin/env python3
"""Fail if local real-data artifacts are tracked by git."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SYNTHETIC = {"data/frozen/fixtures/transactions.ofx"}
FORBIDDEN_NAMES = {".env", "credentials", "secrets", "token", "password"}
FORBIDDEN_SUFFIXES = (".pdf", ".sqlite", ".sqlite3", ".db", ".index")


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True, capture_output=True, text=False,
    )
    return [name.decode() for name in result.stdout.split(b"\0") if name]


def main() -> None:
    bad = []
    for name in tracked_files():
        path = Path(name)
        lower = name.lower()
        parts = {part.lower() for part in path.parts}
        if any(part in {"local", "real", "raw", "derived", "manifests"} for part in parts) and name not in {
            "data/frozen/fixtures/transactions.ofx"
        }:
            # Existing synthetic data is deliberately outside these local-only directories.
            bad.append(f"local-data path: {name}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            bad.append(f"forbidden artifact: {name}")
        if any(token in lower for token in FORBIDDEN_NAMES) and name != ".env.example":
            bad.append(f"credential-like path: {name}")
    if bad:
        print("Tracked local-data artifacts detected:", file=sys.stderr)
        print("\n".join(sorted(set(bad))), file=sys.stderr)
        raise SystemExit(1)
    print("local-data guard: clean")


if __name__ == "__main__":
    main()
