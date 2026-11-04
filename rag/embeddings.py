"""Embedding providers.

Default: `HashingEmbedder` — deterministic, offline, no model download. It hashes
canonicalized unigrams + bigrams into a fixed-dimension vector. Quality is
lexical-level, which is adequate for a curated, small corpus of approved
recovery content and makes tests reproducible. Swap to OpenAI or Ollama
embeddings via EMBEDDING_PROVIDER (then run `make reindex`).
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from collections import Counter

import httpx

from rag.text import content_terms


class EmbeddingProvider(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder(EmbeddingProvider):
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hashing-v1-{dim}"

    def _features(self, text: str) -> Counter:
        terms = content_terms(text)
        feats: Counter = Counter(terms)
        for a, b in zip(terms, terms[1:]):
            feats[f"{a}_{b}"] += 0.5
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat, tf in self._features(text).items():
                h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                vec[idx] += sign * (1.0 + math.log(1.0 + tf))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class OpenAIEmbedder(EmbeddingProvider):
    def __init__(self, api_key: str, dim: int, model: str = "text-embedding-3-small"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model, self.dim, self.name = model, dim, f"openai-{model}-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        return [d.embedding for d in resp.data]


class OllamaEmbedder(EmbeddingProvider):
    def __init__(self, base_url: str, dim: int, model: str = "nomic-embed-text"):
        self.base_url, self.model, self.dim, self.name = base_url.rstrip("/"), model, dim, f"ollama-{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}, timeout=60)
        resp.raise_for_status()
        vectors = resp.json()["embeddings"]
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(f"Ollama model returns dim {len(vectors[0])}; set EMBEDDING_DIM accordingly")
        return vectors


_cached: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _cached
    if _cached is None:
        from app.core.config import get_settings

        s = get_settings()
        if s.embedding_provider == "openai" and s.openai_api_key:
            _cached = OpenAIEmbedder(s.openai_api_key, s.embedding_dim)
        elif s.embedding_provider == "ollama":
            _cached = OllamaEmbedder(s.ollama_base_url, s.embedding_dim)
        else:
            _cached = HashingEmbedder(s.embedding_dim)
    return _cached
