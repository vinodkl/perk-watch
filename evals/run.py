"""Evaluate the tool agent against a synthetic, deterministic fixture."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from openai import OpenAI
from fixture import FixtureEmbedder, open_fixture
from harness import run_case


def main() -> int:
    cases = json.loads((ROOT / "evals/cases.json").read_text(encoding="utf-8"))
    client = OpenAI()
    model = os.getenv("PERKWATCH_EVAL_JUDGE_MODEL", "gpt-4o-mini")
    embedder = FixtureEmbedder()
    results = []
    api_usage = {"calls": 0, "tokens": 0, "failures": 0, "retries": 0}
    with open_fixture(ROOT / "evals/fixture.sqlite") as db:
        for case in cases:
            results.append(run_case(db, case, client=client, embedder=embedder, model=model, api_usage=api_usage))
    report = {"fixture": "evals/fixture.sqlite (synthetic; rebuilt for this run)",
              "passed": sum(not item["fixture_check_failures"] for item in results),
              "live_agent_passed": sum(not item["live_agent_failures"] for item in results),
              "total": len(results), "tool_selection": "live model; deterministic planned calls also checked",
              "api_usage": api_usage, "results": results}
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return int(any(item["fixture_check_failures"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
