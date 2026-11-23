"""Ingestion: PDF -> page-tagged text chunks, workbook -> structured tables."""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries


# --------------------------------------------------------------------------- PDF
@dataclass(frozen=True)
class Chunk:
    id: str
    page: int  # 1-based
    text: str


def extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    with pdfplumber.open(path) as pdf:
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages)]


_SENT = re.compile(r"(?<=[.!?])\s+")


def chunk_pages(pages: list[tuple[int, str]], max_chars: int = 700) -> list[Chunk]:
    """Sentence-packed chunks that never cross a page boundary (so every chunk
    has exactly one page to cite). One sentence of overlap between chunks."""
    chunks: list[Chunk] = []
    for page, text in pages:
        sentences = [s.strip() for s in _SENT.split(re.sub(r"\s+", " ", text)) if s.strip()]
        buf: list[str] = []
        for s in sentences:
            if buf and sum(len(x) + 1 for x in buf) + len(s) > max_chars:
                chunks.append(Chunk(f"p{page}-{len(chunks)}", page, " ".join(buf)))
                buf = buf[-1:]  # overlap
            buf.append(s)
        if buf:
            chunks.append(Chunk(f"p{page}-{len(chunks)}", page, " ".join(buf)))
    return chunks


# ---------------------------------------------------------------------- Workbook
@dataclass
class CellValue:
    value: object
    cell: str  # e.g. "F6"
    number_format: str = "General"


@dataclass
class Row:
    label: str                       # first text cell, e.g. "Task 3"
    texts: list[str]                 # every text cell in the row (used for matching)
    cells: dict[str, CellValue]      # header -> value


@dataclass
class Table:
    sheet: str
    headers: list[str]
    rows: list[Row] = field(default_factory=list)

    def numeric_headers(self) -> list[str]:
        out = []
        for h in self.headers:
            vals = [r.cells[h].value for r in self.rows if h in r.cells and r.cells[h].value is not None]
            if vals and sum(isinstance(v, (int, float)) for v in vals) / len(vals) >= 0.6:
                out.append(h)
        return out


class FormulaEvaluator:
    """Minimal evaluator for workbooks whose formula results are not cached
    (files written by openpyxl/pandas). Supports cell refs, cross-sheet refs,
    + - * / and SUM/AVERAGE/MIN/MAX over ranges. Anything else -> None."""

    _FUNC = re.compile(r"\b(SUM|AVERAGE|MIN|MAX)\(([^()]*)\)", re.I)
    _REF = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_]\w*))!)?\$?([A-Z]{1,3})\$?(\d+)")
    _OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}

    def __init__(self, values_wb, formulas_wb):
        self.values, self.formulas = values_wb, formulas_wb
        self.cache: dict[tuple[str, str], object] = {}

    def get(self, sheet: str, coord: str, _stack: frozenset = frozenset()):
        key = (sheet, coord)
        if key in self.cache:
            return self.cache[key]
        v = self.values[sheet][coord].value
        if v is None:
            f = self.formulas[sheet][coord].value
            if isinstance(f, str) and f.startswith("=") and key not in _stack:
                try:
                    v = self._eval(sheet, f[1:], _stack | {key})
                except Exception:
                    v = None
        self.cache[key] = v
        return v

    def _range_values(self, sheet: str, arg: str, stack) -> list[float]:
        arg = arg.strip()
        m = re.fullmatch(r"(?:(?:'([^']+)'|([A-Za-z_]\w*))!)?(\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?)", arg)
        if not m:
            return [float(arg)]
        sh = m.group(1) or m.group(2) or sheet
        min_col, min_row, max_col, max_row = range_boundaries(m.group(3).replace("$", ""))
        out = []
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                v = self.get(sh, f"{get_column_letter(c)}{r}", stack)
                if isinstance(v, (int, float)):
                    out.append(v)
        return out

    def _eval(self, sheet: str, expr: str, stack):
        def fn(m):
            vals = [x for a in m.group(2).split(",") for x in self._range_values(sheet, a, stack)]
            name = m.group(1).upper()
            res = {"SUM": sum, "MIN": min, "MAX": max,
                   "AVERAGE": lambda v: sum(v) / len(v)}[name](vals)
            return repr(res)

        while self._FUNC.search(expr):
            expr = self._FUNC.sub(fn, expr)

        def ref(m):
            sh = m.group(1) or m.group(2) or sheet
            v = self.get(sh, f"{m.group(3)}{m.group(4)}", stack)
            if not isinstance(v, (int, float)):
                raise ValueError(f"non-numeric ref {m.group(0)}")
            return repr(v)

        expr = self._REF.sub(ref, expr)
        return self._safe(ast.parse(expr, mode="eval").body)

    def _safe(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._OPS:
            return self._OPS[type(node.op)](self._safe(node.left), self._safe(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._OPS:
            return self._OPS[type(node.op)](self._safe(node.operand))
        raise ValueError("unsupported expression")


def _is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != "" and not v.startswith("=")


def extract_workbook(path: Path) -> list[Table]:
    values_wb = load_workbook(path, data_only=True)
    formulas_wb = load_workbook(path, data_only=False)
    ev = FormulaEvaluator(values_wb, formulas_wb)
    tables: list[Table] = []

    for ws in formulas_wb.worksheets:
        header_row = None
        for r in range(1, ws.max_row + 1):
            texts = [c.value for c in ws[r] if _is_text(c.value)]
            if len(texts) >= 2:
                header_row = r
                break
        if header_row is None:
            continue
        cols = {c.column: str(c.value).strip() for c in ws[header_row] if _is_text(c.value)}
        table = Table(sheet=ws.title, headers=list(cols.values()))
        blank_run = 0
        for r in range(header_row + 1, ws.max_row + 1):
            cells: dict[str, CellValue] = {}
            texts: list[str] = []
            for col, header in cols.items():
                coord = f"{get_column_letter(col)}{r}"
                v = ev.get(ws.title, coord)
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                if isinstance(v, str):
                    texts.append(v.strip())
                cells[header] = CellValue(v, coord, values_wb[ws.title][coord].number_format)
            if not cells:
                blank_run += 1
                if blank_run >= 2:
                    break
                continue
            blank_run = 0
            table.rows.append(Row(label=texts[0] if texts else f"Row {r}", texts=texts, cells=cells))
        tables.append(table)
    return tables
