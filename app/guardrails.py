"""Prompt-injection defences for document text.

Layered, because no single layer is sufficient:
1. Routing: exact-number questions never reach the LLM (see router.py).
2. Sanitising: sentences in retrieved chunks that look like instructions to a
   model are removed before the prompt is built (this module).
3. Prompting: chunks are wrapped in <document> tags and the system prompt says
   they are untrusted data (retrieval.py).
4. Output check: money figures in an LLM answer that appear in neither the
   retrieved context nor the workbook are reported as warnings (this module).
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|system)",
    r"\b(system|developer) (note|prompt|message|instruction)s?\b",
    r"\byou (must|should) (now )?(tell|say|answer|respond|reply)\b",
    r"\b(say|answer|respond|reply) (that )?the [\w\s]{0,40}\bis\b",
    r"\byou are now\b",
    r"\bnew instructions?\b",
    r"\b(as an? )?(ai|language model|assistant),? (you|ignore|please)\b",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")
REDACTED = "[removed: text resembling an instruction to the assistant]"


def looks_like_injection(text: str) -> bool:
    return bool(_INJ.search(text))


def sanitize(text: str) -> tuple[str, bool]:
    """Drop instruction-like sentences. Returns (clean_text, was_modified)."""
    out, hit = [], False
    for s in _SENT.split(text):
        if _INJ.search(s):
            hit = True
            if not out or out[-1] != REDACTED:
                out.append(REDACTED)
        else:
            out.append(s)
    return " ".join(out), hit


_MONEY = re.compile(r"[$£€]\s?-?\d[\d,]*(?:\.\d+)?")


def _to_num(s: str) -> float:
    return float(re.sub(r"[^\d.\-]", "", s))


def unsupported_figures(answer: str, context: str, known: set[float]) -> list[str]:
    allowed = {_to_num(m) for m in _MONEY.findall(context)} | known
    return [m for m in _MONEY.findall(answer) if _to_num(m) not in allowed]
