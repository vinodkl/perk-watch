"""User-confirmed usage for manually tracked credits, the app's only runtime write."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .tracker import Marks


def profile_path(root: str | Path) -> Path:
    return Path(root) / "user" / "profile.json"


def load_marks(root: str | Path) -> Marks:
    path = profile_path(root)
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {(row["benefit_id"], row["period_start"]): int(row["amount_minor"]) for row in document.get("marks", [])}


def toggle_mark(root: str | Path, benefit_id: str, period_start: str, amount_minor: int) -> Marks:
    """Mark a period used, or unmark it if it already is. Returns the new marks."""
    marks = load_marks(root)
    key = (benefit_id, period_start)
    if key in marks:
        del marks[key]
    else:
        marks[key] = amount_minor
    _save(root, marks)
    return marks


def _save(root: str | Path, marks: Marks) -> None:
    path = profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"benefit_id": b, "period_start": s, "amount_minor": a} for (b, s), a in sorted(marks.items())]
    # Write then rename so a crash never leaves a half-written profile.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"marks": rows}, handle, indent=2)
    os.replace(tmp, path)
