"""Production embedding provider for official benefit search."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from .privacy import redact_pii


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    """OpenAI embeddings with batching and response-order validation."""

    def __init__(self, client: object | None = None, *, model: str = "text-embedding-3-small",
                 batch_size: int = 128):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=_api_key())
        self.client = client
        self.model = model
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [redact_pii(text) for text in texts[start:start + self.batch_size]]
            response = self.client.embeddings.create(model=self.model, input=batch)
            data = sorted(response.data, key=lambda item: item.index)
            if len(data) != len(batch) or [item.index for item in data] != list(range(len(batch))):
                raise ValueError("embedding response did not preserve every input")
            result.extend([list(item.embedding) for item in data])
        return result


def _api_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    dotenv = Path.cwd() / ".env"
    if not dotenv.exists():
        return None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name == "OPENAI_API_KEY":
            return value.strip().strip("'\"")
    return None
