import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas import AskResponse, Source


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def test_query_response_shape(client):
    r = client.post("/ask", json={"question": "What is the total cost for Task 3?"})
    assert r.status_code == 200
    body = AskResponse.model_validate(r.json())
    assert body.method == "query" and body.value == 85750
    assert body.sources[0].model_dump(include={"type", "sheet", "cell"}) == \
        {"type": "xlsx", "sheet": "Task Costs", "cell": "F6"}


def test_retrieval_response_shape(client):
    body = AskResponse.model_validate(client.post("/ask", json={"question": "What risks are identified?"}).json())
    assert body.method == "retrieval"
    assert body.sources and all(s.type == "pdf" and s.page >= 1 for s in body.sources)


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 501}, {"question": "ok?", "extra": 1}])
def test_bad_requests_rejected(client, payload):
    assert client.post("/ask", json=payload).status_code == 422


@pytest.mark.parametrize("kwargs", [
    {"type": "pdf"},                                  # no page
    {"type": "pdf", "page": 2, "cell": "A1"},         # mixed location
    {"type": "xlsx", "sheet": "S"},                   # no cell
    {"type": "xlsx", "sheet": "S", "cell": "not-a-cell"},
])
def test_invalid_sources_rejected(kwargs):
    with pytest.raises(ValidationError):
        Source(**kwargs)


def test_query_answer_requires_cell_source():
    with pytest.raises(ValidationError):
        AskResponse(question="q", answer="a", method="query", value=1.0,
                    sources=[Source(type="pdf", page=1)])
