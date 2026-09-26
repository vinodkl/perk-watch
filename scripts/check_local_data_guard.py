#!/usr/bin/env python3
"""Fail if local inputs or generated stores are tracked by git."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".pdf", ".sqlite", ".sqlite3", ".db", ".index"}

def main() -> None:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True)
    bad = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        name = raw.decode()
        path = Path(name)
        lower = name.lower()
        if ("/data/real" in lower or "/raw/" in lower or "/prepared/" in lower) and "evals/data/frozen" not in lower:
            bad.append(name)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            bad.append(name)
    if bad:
        print("tracked local-data artifacts detected:", *sorted(set(bad)), sep="\n", file=sys.stderr)
        raise SystemExit(1)
    print("local-data guard: clean")

if __name__ == "__main__":
    main()
