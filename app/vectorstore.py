"""Vector stores: pgvector (primary) and in-memory numpy (tests / no Docker)."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from app.ingest import Chunk


class VectorStore(Protocol):
    def reset(self) -> None: ...
    def add(self, chunks: list[Chunk], vectors: np.ndarray) -> None: ...
    def search(self, vector: np.ndarray, k: int) -> list[tuple[Chunk, float]]: ...


class InMemoryStore:
    def __init__(self):
        self.reset()

    def reset(self):
        self.chunks: list[Chunk] = []
        self.matrix: np.ndarray | None = None

    def add(self, chunks, vectors):
        self.chunks += chunks
        self.matrix = vectors if self.matrix is None else np.vstack([self.matrix, vectors])

    def search(self, vector, k):
        if self.matrix is None:
            return []
        scores = self.matrix @ vector  # vectors are L2-normalised -> cosine
        idx = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in idx]


class PgVectorStore:
    """One table of chunks with an HNSW cosine index. Re-ingest replaces the
    table contents, so the store always mirrors the current files."""

    def __init__(self, dsn: str, dim: int, table: str = "doc_chunks"):
        import psycopg
        from pgvector.psycopg import register_vector

        self.table, self.dim = table, dim
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, page INT NOT NULL, content TEXT NOT NULL,
                    embedding vector({dim}) NOT NULL)""")
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)")

    def reset(self):
        self.conn.execute(f"TRUNCATE {self.table}")

    def add(self, chunks, vectors):
        with self.conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self.table} (id, page, content, embedding) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET page = EXCLUDED.page, content = EXCLUDED.content, "
                "embedding = EXCLUDED.embedding",
                [(c.id, c.page, c.text, v) for c, v in zip(chunks, vectors)])

    def search(self, vector, k):
        rows = self.conn.execute(
            f"SELECT id, page, content, 1 - (embedding <=> %s) AS score FROM {self.table} "
            "ORDER BY embedding <=> %s LIMIT %s", (vector, vector, k)).fetchall()
        return [(Chunk(r[0], r[1], r[2]), float(r[3])) for r in rows]
