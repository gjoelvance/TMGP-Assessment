"""Run the evaluation set and print a score.

    python -m eval.run_eval                      # in-process, uses .env settings
    python -m eval.run_eval --url http://localhost:8000   # against a running server

Scoring (1 point per question, all conditions must hold):
  query     -> method == "query", value == expected_value, source cell == expected_source
  retrieval -> method == "retrieval", >= min_keywords of expected_keywords in the answer
               ("a|b" = either), and at least one cited page in expected_pages
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def grade(item: dict, resp: dict) -> tuple[bool, str]:
    if resp["method"] != item["method"]:
        return False, f"method {resp['method']} != {item['method']}"
    if item["method"] == "query":
        src = next((f"{s['sheet']}!{s['cell']}" for s in resp["sources"] if s["type"] == "xlsx"), None)
        if resp.get("value") is None or abs(resp["value"] - item["expected_value"]) > 1e-6:
            return False, f"value {resp.get('value')} != {item['expected_value']}"
        if src != item["expected_source"]:
            return False, f"source {src} != {item['expected_source']}"
        return True, "ok"
    answer = resp["answer"].lower()
    hits = [k for k in item["expected_keywords"] if any(re.search(re.escape(a), answer) for a in k.split("|"))]
    pages = {s.get("page") for s in resp["sources"]}
    if len(hits) < item["min_keywords"]:
        return False, f"keywords {hits} < {item['min_keywords']}"
    if not pages & set(item["expected_pages"]):
        return False, f"pages {sorted(p for p in pages if p)} miss {item['expected_pages']}"
    return True, f"keywords {hits}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--set", default=str(Path(__file__).with_name("eval_set.json")))
    a = ap.parse_args()
    items = json.loads(Path(a.set).read_text())

    if a.url:
        import httpx
        ask = lambda q: httpx.post(f"{a.url}/ask", json={"question": q}, timeout=120).json()  # noqa: E731
    else:
        from app.config import build_service
        svc = build_service()
        print(f"LLM: {svc.llm.name}  embedder: {type(svc.embedder).__name__}  store: {type(svc.store).__name__}\n")
        ask = lambda q: svc.ask(q).model_dump()  # noqa: E731

    score = 0
    for it in items:
        resp = ask(it["question"])
        ok, why = grade(it, resp)
        score += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {it['id']:>2}. {it['question']}\n"
              f"        {resp['method']}: {resp['answer'][:150]}\n        {why}")
    print(f"\nScore: {score}/{len(items)} ({100 * score / len(items):.0f}%)")


if __name__ == "__main__":
    main()
