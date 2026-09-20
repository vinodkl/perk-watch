#!/usr/bin/env python3
"""Measure an OpenAI reranker against the retained per-benefit baseline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openai import OpenAI
from perk_watch.community_rag import baseline, load_served_ideas, rerank, retrieval_metrics


def paths(root: Path) -> list[Path]:
    result = []
    for pointer in sorted((root / "prepared/community").glob("*/current.json")):
        current = json.loads(pointer.read_text(encoding="utf-8"))
        result.append(root / current["path"] / "served_ideas.json")
    return result


def llm_reranker(client, model: str):
    def rank(query: str, rows: list[dict[str, object]]) -> list[str]:
        choices = [{"idea_id": row["idea_id"], "idea": row["idea"], "excerpt": row["excerpt"]} for row in rows]
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": (
                "Rank these non-authoritative community ideas for the query. "
                "Return JSON only as {\"idea_ids\":[...]} containing every idea_id exactly once. "
                f"Query: {query}\nIdeas: {json.dumps(choices, sort_keys=True)}"
            )}],
            response_format={"type": "json_object"},
        )
        order = json.loads(response.choices[0].message.content)["idea_ids"]
        expected = {row["idea_id"] for row in rows}
        if set(order) != expected or len(order) != len(expected):
            raise ValueError("reranker did not return an exact idea-id permutation")
        return order
    return rank


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("OPENAI_RERANK_MODEL", "gpt-4o-mini"))
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for the genuine reranker evaluation")
    root = Path(os.environ.get("PERKWATCH_DATA_DIR", Path.home() / ".local/share/perk-watch"))
    ideas = load_served_ideas(paths(root))
    terms = sorted({row["terms_version"] for row in ideas})
    if len(terms) != 1:
        raise SystemExit(f"expected one current terms version, found {terms}")
    queries = []
    failures = []
    rank = llm_reranker(OpenAI(api_key=os.environ["OPENAI_API_KEY"]), args.model)
    for benefit_id in sorted({row["benefit_id"] for row in ideas}):
        rows = baseline(ideas, benefit_id=benefit_id, terms_version=terms[0])
        query = next(row["idea"] for row in rows)
        before = [row["idea_id"] for row in rows]
        try:
            after_rows = rerank(query, rows, rank)
            after = [row["idea_id"] for row in after_rows]
        except Exception as exc:  # record exact per-query failure, keep denominator honest
            after = []
            failures.append({"benefit_id": benefit_id, "error": f"{type(exc).__name__}: {exc}"})
        queries.append({"benefit_id": benefit_id, "retrieved": before, "relevant": before,
                        "rows": rows, "reranked": after})
    before_metrics = retrieval_metrics(queries)
    after_metrics = retrieval_metrics([{**q, "retrieved": q["reranked"]} for q in queries])
    print(json.dumps({
        "corpus_versions": sorted({row["corpus_version"] for row in ideas}),
        "terms_version": terms[0], "model": args.model,
        "query_count": len(queries), "served_idea_count": len(ideas),
        "before": before_metrics, "after": after_metrics,
        "failures": failures,
        "retain_reranker": not failures and after_metrics["mrr"]["value"] > before_metrics["mrr"]["value"],
        "coverage_gaps": ["one served idea per benefit makes ranking improvement impossible",
                          "queries are corpus-derived, not human relevance labels"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
