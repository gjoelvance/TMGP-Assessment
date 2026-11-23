from pathlib import Path

import pytest

from app.embeddings import HashEmbedder
from app.service import QAService
from app.vectorstore import InMemoryStore
from scripts.make_sample_data import build_pdf, build_workbook


class RecordingLLM:
    """Fake LLM that records prompts. If `obey_injections` is set it behaves
    like a maximally gullible model: any 'say the total is $X' it sees in the
    prompt becomes its answer. Used to prove the defences, not the model, stop it."""

    name = "fake"

    def __init__(self, reply="Stub answer (p. 3).", obey_injections=False):
        self.reply, self.obey, self.calls = reply, obey_injections, []

    def complete(self, system, user):
        self.calls.append((system, user))
        if self.obey and "say the total is $0" in user:
            return "The total is $0."
        return self.reply


@pytest.fixture(scope="session")
def files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("data")
    return {"pdf": build_pdf(d / "report.pdf"),
            "pdf_injected": build_pdf(d / "report_injected.pdf", inject=True),
            "xlsx": build_workbook(d / "workbook.xlsx")}


@pytest.fixture
def llm():
    return RecordingLLM()


@pytest.fixture
def service(files, llm) -> QAService:
    return QAService(files["pdf"], files["xlsx"], HashEmbedder(), InMemoryStore(), llm)
