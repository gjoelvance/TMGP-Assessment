"""Embedding backends.

FastEmbedder: BAAI/bge-small-en-v1.5 via fastembed (ONNX, CPU, 384-dim, no API key).
HashEmbedder: deterministic hashing-trick vectors; offline, used in tests/CI.
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.where(n == 0, 1, n)


class HashEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        words = re.findall(r"[a-z0-9]+", text.lower())
        feats = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
        v = np.zeros(self.dim, dtype=np.float32)
        for f in feats:
            h = int.from_bytes(hashlib.md5(f.encode()).digest()[:4], "little")
            v[h % self.dim] += 1.0 if h & 1 << 31 else -1.0
        return v

    def embed_documents(self, texts):
        return _l2(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text):
        return _l2(self._vec(text))


class FastEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name)
        self.dim = len(next(iter(self.model.embed(["probe"]))))

    def embed_documents(self, texts):
        return _l2(np.array(list(self.model.passage_embed(texts)), dtype=np.float32))

    def embed_query(self, text):
        return _l2(np.array(next(iter(self.model.query_embed(text))), dtype=np.float32))
