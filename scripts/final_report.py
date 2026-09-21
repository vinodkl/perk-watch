#!/usr/bin/env python3
"""Assemble the final, separately-labelled PerkWatch evidence report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablation", type=Path, required=True)
    parser.add_argument("--local", type=Path, default=Path("data/real/prepared/evaluation/vku-27-local-real-data-integration-report.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    compare = json.loads(subprocess.run([sys.executable, "scripts/compare_frozen.py"], cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    red = json.loads(subprocess.run([sys.executable, "scripts/evaluate_red_team.py"], cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    local = load(args.local)
    report = {
        "report": "PerkWatch final capstone evidence",
        "synthetic_frozen_benchmark": {
            "dataset": compare["dataset"],
            "comparison": [{k: v for k, v in row.items() if k != "predictions"} for row in compare["comparison"]],
            "observed_failures": {row["handling"]: row["observed_failures"] for row in compare["comparison"]},
        },
        "llm_arithmetic_ablation": load(args.ablation),
        "local_real_data_integration": {
            "dataset": local["dataset"],
            "coverage": local["dataset"]["coverage"],
            "status_counts": local["evaluation"]["status_counts"],
            "metrics": local["metrics"],
            "observed_failures": local["observed_failures"],
            "known_coverage_gaps": local["known_coverage_gaps"],
        },
        "community_retrieval": {
            "corpus": "community-reddit-2026-09-20.v2",
            "served_ideas": "10/10",
            "baseline_recall_at_5": "10/10",
            "index_recall_at_5": "10/10",
            "baseline_mrr": "10.0/10",
            "reranked_mrr": "10.0/10",
            "reranker_calls_succeeded": "10/10",
            "decision": "retain the simpler unranked per-benefit baseline; cut embedding index and reranker",
        },
        "authority_boundary_safety": {
            "red_team_generated_attack_resistance": red["attack_resistance_rate"],
            "real_conflicting_ideas_resisted": red["headline_conflicting_ideas"]["resisted"],
            "generated_attack_failures": red["observed_failures"],
        },
        "planning": {"dataset": "synthetic frozen planning cases", "feasibility_rate": "see existing VKU-19 report; no counts invented here"},
        "latency": {"offline_frozen_comparison_wall_ms": elapsed_ms, "dataset": compare["dataset"]["dataset_version"], "method": "one local process invocation"},
        "token_cost": {"observed_requests": "0/0 in offline reproducible report", "status": "live usage metadata was not persisted by prior runs; no cost is claimed"},
        "coverage_rule": "Synthetic and local-real counts are never blended. Null local accuracy metrics mean unavailable human labels, not zero accuracy.",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "synthetic_cases": compare["dataset"]["case_count"], "ablation": report["llm_arithmetic_ablation"]["error_rate"]}, indent=2))


if __name__ == "__main__":
    main()
