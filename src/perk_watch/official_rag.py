"""Official benefit-clause embeddings and metadata-filtered exact retrieval."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

DEFAULT_MODEL = "text-embedding-3-small"
INDEX_RELATIVE_PATH = Path("prepared/indexes/official")


class EmbeddingClient(Protocol):
    def create(self, *, model: str, input: str | list[str]) -> Any: ...


class OpenAIEmbeddingClient:
    """Small adapter so indexing and tests can inject the embedding call."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        self.client = client

    def create(self, *, model: str, input: str | list[str]) -> Any:
        return self.client.embeddings.create(model=model, input=input)


class OfficialClauseIndex:
    def __init__(self, index_dir: str | Path) -> None:
        self.index_dir = Path(index_dir)
        self.manifest = _read(self.index_dir / "manifest.json")
        self.metadata = _read(self.index_dir / "metadata.json")["clauses"]
        self.embeddings = np.load(self.index_dir / "embeddings.npy")

    @classmethod
    def build(
        cls, corpus_path: str | Path, index_dir: str | Path, embedder: EmbeddingClient,
        *, model: str = DEFAULT_MODEL,
    ) -> "OfficialClauseIndex":
        corpus = _read(Path(corpus_path))
        clauses = corpus.get("clauses", [])
        metadata = [_metadata(row, corpus) for row in clauses]
        vectors = _embed(embedder, model, [row["text"] for row in clauses])
        if len(vectors) != len(metadata):
            raise ValueError("embedding count does not match clause count")
        target = Path(index_dir)
        target.mkdir(parents=True, exist_ok=True)
        np.save(target / "embeddings.npy", vectors)
        (target / "metadata.json").write_text(json.dumps({"clauses": metadata}, indent=2, sort_keys=True) + "\n")
        (target / "manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "corpus_terms_version": corpus.get("terms_version"),
            "embedding_model": model,
            "clause_count": len(metadata),
        }, indent=2, sort_keys=True) + "\n")
        return cls(target)

    def search(
        self, query: str, *, card_id: str | None = None, benefit_id: str | None = None,
        as_of: str | date | None = None, terms_version: str | None = None,
        issuer_id: str | None = None, top_k: int = 5, embedder: EmbeddingClient,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            return []
        filters = [row for row in self.metadata if _matches(
            row, card_id=card_id, benefit_id=benefit_id, as_of=as_of,
            terms_version=terms_version, issuer_id=issuer_id,
        )]
        if not filters:
            return []
        query_vector = _embed(embedder, self.manifest["embedding_model"], [query])[0]
        norms = np.linalg.norm(self.embeddings, axis=1)
        query_norm = np.linalg.norm(query_vector)
        if not query_norm:
            raise ValueError("query embedding has zero norm")
        scores = self.embeddings @ query_vector / np.maximum(norms * query_norm, 1e-12)
        allowed = {row["clause_id"] for row in filters}
        ranked = sorted(
            ((float(scores[index]), row) for index, row in enumerate(self.metadata) if row["clause_id"] in allowed),
            key=lambda item: (-item[0], item[1]["clause_id"]),
        )[:top_k]
        return [row | {"score": score} for score, row in ranked]


def build_official_index(root: str | Path, embedder: EmbeddingClient, *, model: str = DEFAULT_MODEL) -> OfficialClauseIndex:
    root = Path(root)
    return OfficialClauseIndex.build(
        root / "prepared/benefits/current.json", root / INDEX_RELATIVE_PATH, embedder, model=model,
    )


def _metadata(row: Mapping[str, Any], corpus: Mapping[str, Any]) -> dict[str, Any]:
    source_id = str(row.get("source_id") or row.get("source_ref") or "")
    source = corpus.get("sources", {}).get(source_id, {})
    card_id = row.get("card_id") or source.get("card_id") or source_id.split(":", 1)[0] or None
    return {
        "clause_id": row["clause_id"], "clause_text": row["text"],
        "source_id": source_id, "citation": row.get("source_ref") or source_id,
        "citations": [row.get("source_ref") or source_id],
        "effective_from": row.get("effective_from"), "effective_to": row.get("effective_to"),
        "terms_version": corpus.get("terms_version") or row.get("terms_version"),
        "source_terms_version": row.get("terms_version"),
        "card_id": card_id, "benefit_id": row.get("benefit_id"),
        "issuer_id": row.get("issuer_id") or (str(card_id).split("_", 1)[0] if card_id else None),
    }


def _matches(row: Mapping[str, Any], *, card_id: str | None, benefit_id: str | None,
             as_of: str | date | None, terms_version: str | None, issuer_id: str | None) -> bool:
    if card_id is not None and row.get("card_id") != card_id:
        return False
    if benefit_id is not None and row.get("benefit_id") != benefit_id:
        return False
    if issuer_id is not None and row.get("issuer_id") != issuer_id:
        return False
    if terms_version is not None and row.get("terms_version") != terms_version:
        return False
    if as_of is None:
        return True
    point = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
    return (not row.get("effective_from") or row["effective_from"] <= point) and (
        not row.get("effective_to") or point <= row["effective_to"]
    )


def _embed(embedder: EmbeddingClient, model: str, texts: Sequence[str]) -> np.ndarray:
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    response = embedder.create(model=model, input=list(texts))
    rows = sorted(response.data, key=lambda item: item.index)
    return np.asarray([item.embedding for item in rows], dtype=np.float32)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
