"""Deterministic lookups over workbook tables. No LLM involved.

A question resolves to (row, column) by matching row text cells and column
headers against the question's words. If no row is named but the question asks
for a total, the sheet's Total row is used (or the column is summed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingest import Table

STOP = {"the", "a", "an", "of", "for", "in", "is", "what", "was", "were", "are", "to", "and",
        "how", "much", "many", "does", "do", "did", "on", "by", "with", "at", "which", "s"}
SYNONYMS = {"labor": "labour", "spend": "spent", "costs": "cost", "weeks": "weeks",
            "materials": "material", "subcontractor": "subcontract", "budgeted": "budget",
            "overspend": "variance", "overrun": "variance", "length": "duration", "long": "duration"}
GENERIC = {"cost", "total", "amount", "value", "spent", "figure"}
TOTAL_LABELS = {"total", "grand total", "totals", "sum", "overall"}
NAMED_ENTITY = re.compile(r"\b[A-Za-z]+[ -]?\d+\b")  # "Task 99", "Q5", "Phase-2"
AGGREGATE_CUES =re.compile(r"\b(total|overall|all tasks|altogether|combined|whole project|entire|sum)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9£$€% ]", " ", s.lower())).strip()


def _tokens(s: str) -> set[str]:
    out = set()
    for t in _norm(s).split():
        t = SYNONYMS.get(t, t)
        if t not in STOP and t not in {"$", "£", "€"}:
            out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)
    return out


def _contains_phrase(question_norm: str, phrase: str) -> bool:
    p = _norm(phrase)
    return bool(p) and re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", question_norm) is not None


@dataclass
class QueryResult:
    answer: str
    value: float
    sheet: str
    cell: str
    row_label: str
    column: str


def display_header(h: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", h).strip() or h


def format_value(v: float, header: str, number_format: str = "") -> str:
    sym = next((c for c in "$£€" if c in header or c in number_format), "")
    num = f"{abs(v):,.0f}" if float(v).is_integer() else f"{abs(v):,.2f}"
    unit = ""
    m = re.search(r"\(([^)$£€]+)\)", header)
    if m and not sym:
        unit = " " + m.group(1).strip()
    return f"{'-' if v < 0 else ''}{sym}{num}{unit}"


class StructuredIndex:
    def __init__(self, tables: list[Table]):
        self.tables = tables

    # --- matching -----------------------------------------------------------
    def _match_column(self, table: Table, q_tokens: set[str]) -> tuple[str | None, float]:
        best, best_score = None, 0.0
        for h in table.numeric_headers():
            ht = _tokens(h)
            hits = ht & q_tokens
            if not hits:
                continue
            # generic words count half, so "labour cost" -> Labour, not Total Cost
            score = sum(0.5 if t in GENERIC else 1.0 for t in hits)
            score += 0.1 if "total" in ht else 0   # bare "cost" -> Total Cost
            score -= 0.01 * len(ht - q_tokens)     # prefer tighter headers
            if score > best_score:
                best, best_score = h, score
        return best, best_score

    def _match_row(self, table: Table, q_norm: str):
        best, best_len = None, 0
        for row in table.rows:
            if row.label.lower() in TOTAL_LABELS:
                continue
            for text in row.texts:
                if _contains_phrase(q_norm, text) and len(text) > best_len:
                    best, best_len = row, len(text)
        return best

    def _total_row(self, table: Table):
        return next((r for r in table.rows if r.label.lower() in TOTAL_LABELS), None)

    # --- public -------------------------------------------------------------
    def lookup(self, question: str) -> QueryResult | None:
        q_norm, q_tokens = _norm(question), _tokens(question)
        candidates = []
        for table in self.tables:
            col, col_score = self._match_column(table, q_tokens)
            if not col:
                continue
            row = self._match_row(table, q_norm)
            if row is not None and col in row.cells:
                candidates.append((2 + col_score, table, row, col))
            elif row is None and AGGREGATE_CUES.search(question) and not NAMED_ENTITY.search(question):
                # "total for Task 99" must not silently become the grand total
                candidates.append((1 + col_score, table, None, col))
        if not candidates:
            return None
        _, table, row, col = max(candidates, key=lambda c: c[0])
        label = display_header(col)

        if row is not None:
            cv = row.cells[col]
            v = float(cv.value)
            return QueryResult(f"The {label} for {row.label} is {format_value(v, col, cv.number_format)}.",
                               v, table.sheet, cv.cell, row.label, col)

        total = self._total_row(table)
        if total is not None and col in total.cells:
            cv = total.cells[col]
            v = float(cv.value)
            return QueryResult(f"The overall {label} is {format_value(v, col, cv.number_format)}.",
                               v, table.sheet, cv.cell, total.label, col)

        cells = [r.cells[col] for r in table.rows if col in r.cells and isinstance(r.cells[col].value, (int, float))]
        v = float(sum(c.value for c in cells))
        rng = f"{cells[0].cell}:{cells[-1].cell}"
        return QueryResult(f"The sum of {label} across {len(cells)} rows is "
                           f"{format_value(v, col, cells[0].number_format)}.", v, table.sheet, rng, "(sum)", col)

    def all_numbers(self) -> set[float]:
        return {float(cv.value) for t in self.tables for r in t.rows for cv in r.cells.values()
                if isinstance(cv.value, (int, float))}
