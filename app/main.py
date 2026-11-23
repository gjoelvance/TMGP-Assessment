"""FastAPI app.  Run:  uvicorn app.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.schemas import AskRequest, AskResponse
from app.service import QAService


def create_app(service: QAService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is None:
            from app.config import build_service
            app.state.service = build_service()
        else:
            app.state.service = service
        yield

    app = FastAPI(title="Document Q&A", lifespan=lifespan)

    @app.get("/health")
    def health(request: Request):
        s: QAService = request.app.state.service
        return {"status": "ok", "chunks": len(s.chunks), "tables": [t.sheet for t in s.index.tables],
                "llm": s.llm.name}

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request) -> AskResponse:
        return request.app.state.service.ask(body.question)

    return app


app = create_app()
