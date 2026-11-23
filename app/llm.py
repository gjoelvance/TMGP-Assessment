"""LLM backends: Anthropic Claude, plus an offline extractive fallback."""
from __future__ import annotations

import re
from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low"):
        import anthropic

        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model, self.effort = model, effort
        self.name = f"anthropic:{model}"

    def complete(self, system: str, user: str) -> str:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            # if a safety classifier declines, retry server-side on a fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return "The model declined to answer this question."
        return "".join(b.text for b in resp.content if b.type == "text").strip()


class ExtractiveLLM:
    """No-API-key fallback: returns the context sentences that overlap most
    with the question. Never invents text, so it cannot be 'instructed'."""

    name = "extractive"
    _DOC = re.compile(r'<document page="(\d+)">\s*(.*?)\s*</document>', re.S)
    _STOP = {"the", "a", "an", "of", "and", "to", "in", "is", "what", "does", "do", "for", "on", "why", "how", "are", "report"}

    def complete(self, system: str, user: str) -> str:
        q = user.split("<question>")[-1].split("</question>")[0]
        q_words = {w for w in re.findall(r"[a-z]+", q.lower()) if w not in self._STOP}
        scored = []
        for page, text in self._DOC.findall(user):
            for s in re.split(r"(?<=[.!?])\s+", text):
                if s.startswith("[removed"):
                    continue
                words = set(re.findall(r"[a-z]+", s.lower()))
                stems = {w[:4] for w in words}
                score = sum(1 for w in q_words if w in words or w[:4] in stems)
                if score:
                    scored.append((score, s.strip(), page))
        if not scored:
            return "The report does not say."
        scored.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for _, s, page in scored[:3]:
            if s not in seen:
                seen.add(s)
                out.append(f"{s} (p. {page})")
        return " ".join(out)
