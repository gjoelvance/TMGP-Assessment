"""Settings from environment variables (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from app.embeddings import FastEmbedder, HashEmbedder
from app.llm import AnthropicLLM, ExtractiveLLM
from app.service import QAService
from app.vectorstore import InMemoryStore, PgVectorStore

load_dotenv()


def build_service(pdf_path: str | None = None, xlsx_path: str | None = None) -> QAService:
    pdf = Path(pdf_path or os.getenv("PDF_PATH", "data/report.pdf"))
    xlsx = Path(xlsx_path or os.getenv("XLSX_PATH", "data/workbook.xlsx"))

    embedder = HashEmbedder() if os.getenv("EMBEDDER", "fastembed") == "hash" else \
        FastEmbedder(os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))

    dsn = os.getenv("DATABASE_URL")
    store = PgVectorStore(dsn, embedder.dim) if dsn else InMemoryStore()

    if os.getenv("LLM_PROVIDER", "anthropic") == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        llm = AnthropicLLM(os.getenv("LLM_MODEL", "claude-opus-5-5"), os.getenv("LLM_EFFORT", "low"))
    else:
        llm = ExtractiveLLM()

    return QAService(pdf, xlsx, embedder, store, llm, top_k=int(os.getenv("TOP_K", "4")))
