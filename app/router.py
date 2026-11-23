"""Route a question to a deterministic query or to retrieval + LLM.

Rules, in order:
1. Narrative cues (why, risks, explain, ...) -> retrieval, even if a number is mentioned.
2. Numeric cues AND the structured index can resolve the question -> query.
3. Everything else -> retrieval.

Rule 2 means a question is only answered by "query" when a concrete cell backs
the answer; otherwise we never guess a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.query_engine import QueryResult, StructuredIndex

NARRATIVE = re.compile(
    r"\b(why|explain|describe|summari[sz]e|summary|risks?|mitigat\w*|recommend\w*|lessons?|"
    r"next steps|challenges?|issues?|reasons?|caused?|impact|what happened|discuss|approach)\b", re.I)
NUMERIC = re.compile(
    r"\b(how much|how many|total|cost|amount|value|budget|spend|spent|sum|variance|number|"
    r"labou?r|materials?|subcontract|duration|weeks|planned|actual|figure)\b|[$£€%]", re.I)


@dataclass
class Route:
    method: Literal["query", "retrieval"]
    reason: str
    result: QueryResult | None = None


def route(question: str, index: StructuredIndex) -> Route:
    if NARRATIVE.search(question):
        return Route("retrieval", "narrative cue")
    if NUMERIC.search(question):
        result = index.lookup(question)
        if result is not None:
            return Route("query", "numeric cue resolved to a cell", result)
        return Route("retrieval", "numeric cue but no matching row/column")
    return Route("retrieval", "no numeric cue")
