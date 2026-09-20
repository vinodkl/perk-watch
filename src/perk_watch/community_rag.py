"""Local, non-authoritative community retrieval over reviewed ideas."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

from .official_rag import DEFAULT_MODEL, EmbeddingClient, _embed

COMMUNITY_INDEX_RELATIVE_PATH = Path("prepared/indexes/community")


class Reranker(Protocol):
    def __call__(self, query: str, rows: list[dict[str, Any]]) -> list[str]: ...


class CommunityIdeaIndex:
    """Exact cosine search over only current, reviewed, served ideas."""

    def __init__(self, index_dir: str | Path) -> None:
        self.index_dir = Path(index_dir)
        self.manifest = _read(self.index_dir / "manifest.json")
        self.metadata = _read(self.index_dir / "metadata.json")["ideas"]
        self.embeddings = np.load(self.index_dir / "embeddings.npy")
        if len(self.metadata) != len(self.embeddings):
            raise ValueError("embedding count does not match community idea count")

    @classmethod
    def build(
        cls, corpus_paths: Iterable[str | Path], index_dir: str | Path,
        embedder: EmbeddingClient, *, model: str = DEFAULT_MODEL,
    ) -> "CommunityIdeaIndex":
        ideas = _served(_load_ideas(corpus_paths))
        vectors = _embed(embedder, model, [row["idea"] for row in ideas])
        if len(vectors) != len(ideas):
            raise ValueError("embedding count does not match community idea count")
        target = Path(index_dir)
        target.mkdir(parents=True, exist_ok=True)
        np.save(target / "embeddings.npy", vectors)
        _write(target / "metadata.json", {"ideas": ideas})
        _write(target / "manifest.json", {
            "schema_version": 1, "embedding_model": model,
            "idea_count": len(ideas), "corpus_versions": sorted({row["corpus_version"] for row in ideas}),
            "terms_versions": sorted({row["terms_version"] for row in ideas}),
            "served_only": True, "network_accessed": False,
        })
        return cls(target)

    def search(
        self, query: str, *, benefit_id: str, terms_version: str,
        top_k: int = 5, embedder: EmbeddingClient,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            return []
        allowed = [(i, row) for i, row in enumerate(self.metadata)
                   if row["benefit_id"] == benefit_id and row["terms_version"] == terms_version]
        if not allowed:
            return []
        query_vector = _embed(embedder, self.manifest["embedding_model"], [query])[0]
        query_norm = np.linalg.norm(query_vector)
        if not query_norm:
            raise ValueError("query embedding has zero norm")
        norms = np.linalg.norm(self.embeddings, axis=1)
        scores = self.embeddings @ query_vector / np.maximum(norms * query_norm, 1e-12)
        ranked = sorted(((float(scores[i]), row) for i, row in allowed),
                        key=lambda item: (-item[0], item[1]["idea_id"]))[:top_k]
        return [_public(row) | {"score": score} for score, row in ranked]


def load_served_ideas(corpus_paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load prepared snapshots; conflicts and unclear ideas are rejected."""
    return _served(_load_ideas(corpus_paths))


def baseline(ideas: Iterable[Mapping[str, Any]], *, benefit_id: str, terms_version: str) -> list[dict[str, Any]]:
    served = _served_input(ideas)
    return [_public(row) for row in sorted(
        (row for row in served if row["benefit_id"] == benefit_id and row["terms_version"] == terms_version),
        key=lambda row: str(row["idea_id"]),
    )]


def serve_community(ideas: Iterable[Mapping[str, Any]], *, benefit_ids: Iterable[str], terms_version: str) -> dict[str, Any]:
    """The retained path: return every current served idea, without ranking."""
    served = _served_input(ideas)
    wanted = set(benefit_ids)
    return {
        "available": True,
        "ideas": [row for row in sorted(served, key=lambda row: row["idea_id"])
                  if row["benefit_id"] in wanted and row["terms_version"] == terms_version],
        "labels": ["non-authoritative", "unverified"],
    }


def rerank(query: str, rows: list[dict[str, Any]], model: Reranker) -> list[dict[str, Any]]:
    """Apply an LLM's idea-id ordering without allowing it to change metadata."""
    order = model(query, rows)
    positions = {idea_id: position for position, idea_id in enumerate(order)}
    return sorted(rows, key=lambda row: (positions.get(row["idea_id"], len(order)), row["idea_id"]))


def retrieval_metrics(
    queries: Iterable[Mapping[str, Any]], *, k: int = 5,
) -> dict[str, Any]:
    """Score precomputed results and preserve exact counts for an audit report."""
    queries = list(queries)
    recall_hits = sum(bool(set(q["retrieved"][:k]) & set(q["relevant"])) for q in queries)
    mrr_total = sum(_reciprocal_rank(q["retrieved"], q["relevant"]) for q in queries)
    returned = [row for q in queries for row in q.get("rows", [])]
    verbatim = sum(bool(row.get("quote_verbatim", False)) for row in returned)
    stale = sum(bool(row.get("stale", False)) for row in returned)
    denominator = len(queries)
    row_denominator = len(returned)
    return {
        "recall_at_5": {"numerator": recall_hits, "denominator": denominator,
                        "value": recall_hits / denominator if denominator else None},
        "mrr": {"numerator": mrr_total, "denominator": denominator,
                "value": mrr_total / denominator if denominator else None},
        "quote_verbatim_rate": {"numerator": verbatim, "denominator": row_denominator,
                                "value": verbatim / row_denominator if row_denominator else None},
        "staleness_flag_rate": {"numerator": stale, "denominator": row_denominator,
                                 "value": stale / row_denominator if row_denominator else None},
        "query_count": denominator,
        "returned_row_count": row_denominator,
    }


def _reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    wanted = set(relevant)
    return next((1 / position for position, idea_id in enumerate(retrieved, 1) if idea_id in wanted), 0.0)


def _served_input(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    if rows and all("review_label" not in row for row in rows):
        if not all(row.get("labels") == ["non-authoritative", "unverified"] for row in rows):
            raise ValueError("community input is missing review labels")
        return sorted((dict(row) for row in rows), key=lambda row: row["idea_id"])
    return _served(rows)


def _served(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("review_label") != "no_known_conflict" or row.get("served") is not True:
            continue
        if row.get("review_label") in {"explicit_conflict", "unclear"}:
            raise ValueError("conflicting or unclear idea reached community index")
        result.append(_public(row))
    return sorted(result, key=lambda row: row["idea_id"])


def _public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in (
        "idea_id", "benefit_id", "idea", "excerpt", "source_date", "source_url",
        "corpus_version", "terms_version",
    )} | {"labels": ["non-authoritative", "unverified"]}


def _load_ideas(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        value = _read(Path(path))
        rows.extend(value.get("ideas", []))
    return rows


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
