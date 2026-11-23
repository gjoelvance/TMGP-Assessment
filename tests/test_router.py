import pytest

from app.router import route


@pytest.mark.parametrize("question, value, cell", [
    ("What is the total cost for Task 3?", 85750, "F6"),
    ("What is the cost of Task 3?", 85750, "F6"),
    ("What is the labour cost for Task 1?", 18500, "C4"),
    ("What was the budget for Task 4?", 105000, "G7"),
    ("What was the actual spend in Q2?", 101200, "C3"),
    ("What is the total cost across all tasks?", 322000, "F9"),
])
def test_numeric_questions_route_to_query(service, question, value, cell):
    r = route(question, service.index)
    assert r.method == "query"
    assert r.result.value == value and r.result.cell == cell


@pytest.mark.parametrize("question", [
    "What risks does the report identify?",
    "Why is Task 3 over budget?",                       # number words, but narrative intent
    "Explain the cost position for Task 4",
    "What are the recommended next steps?",
])
def test_narrative_questions_route_to_retrieval(service, question):
    assert route(question, service.index).method == "retrieval"


def test_unresolvable_number_falls_back_not_guessed(service):
    r = route("What is the total cost for Task 99?", service.index)
    assert r.method == "retrieval" and r.result is None


def test_query_does_not_call_llm(service, llm):
    service.ask("What is the total cost for Task 3?")
    assert llm.calls == []


def test_retrieval_calls_llm_with_page_tagged_context(service, llm):
    service.ask("What risks does the report identify?")
    system, user = llm.calls[0]
    assert "untrusted data" in system
    assert '<document page="3">' in user and "<question>" in user
