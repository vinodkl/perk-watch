from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_comparison_is_reproducible_and_separate():
    command = [sys.executable, str(ROOT / "scripts/compare_frozen.py")]
    first = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["dataset"] == {
        "dataset_version": "slice0-2026-09-19.v1",
        "terms_version": "synthetic-2026-09-19.v1",
        "synthetic": True,
        "case_count": 36,
        "category_counts": {
            "calendar_year": 9,
            "cardmember_year": 4,
            "enrollment_required": 9,
            "four_year": 5,
            "monthly": 8,
            "near_miss_descriptor": 5,
            "portal_gated": 12,
            "posting_lag_boundary": 7,
            "quarterly": 6,
            "semiannual": 4,
        },
    }
    assert {row["handling"] for row in report["comparison"]} == {
        "retrieval-based transaction handling", "tool-based transaction handling"
    }
    assert report["comparison"][1]["benefit_status_accuracy"] == "36/36"
    assert report["comparison"][1]["remaining_value_accuracy"] == "36/36"
    assert report["comparison"][1]["deadline_accuracy"] == "36/36"
    assert report["comparison"][0]["observed_failures"]
    assert "VKU-27" in report["known_coverage_gaps"][0]
