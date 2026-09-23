"""Rewrite every eval question once and cache the result — Phase 4's controlled input.

    ./.venv/bin/python scripts/cache_rewrites.py            # resumes; skips cached ids

Every retrieval arm then reads the same rewrite, so a temperature-0 wobble in the
rewriter cannot show up as a difference between arms, and Phase 4 retrieval can be
re-scored later without calling the LLM again. Waits out daily-cap 429s in place.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrachat.config import load_config  # noqa: E402
from infrachat.evaluate import load_questions  # noqa: E402
from infrachat.retrieve.rewrite import REWRITE_PROMPT_SHA, build  # noqa: E402

OUT = Path("eval/runs/+rewriter-queries.json")

cfg = load_config("config.yaml")
rewriter = build(cfg.rewrite.model_copy(update={"enabled": True}), cfg.require_llm())
questions = load_questions(Path("eval/questions.yaml"), cfg.source_names)
cache = json.loads(OUT.read_text()) if OUT.exists() else {
    "model": cfg.rewrite.model, "reasoning_effort": cfg.rewrite.reasoning_effort,
    "prompt_sha": REWRITE_PROMPT_SHA, "queries": {}}
if cache["prompt_sha"] != REWRITE_PROMPT_SHA:
    raise SystemExit("rewrite prompt changed since this cache was made — delete it and start over")

for i, q in enumerate(questions, 1):
    if q.id in cache["queries"]:
        continue
    while True:
        try:
            t = time.perf_counter()
            rewritten = rewriter.rewrite(q.question)
            ms = round((time.perf_counter() - t) * 1000)
            break
        except Exception as exc:  # noqa: BLE001
            if "rate limit" in str(exc) or "429" in str(exc):
                print(f"  [{i}] rate limited — waiting 120s", flush=True)
                time.sleep(120)
                continue
            raise
    cache["queries"][q.id] = {"question": q.question, "rewritten": rewritten, "ms": ms}
    OUT.write_text(json.dumps(cache, indent=1))
    print(f"  [{i:>2}/{len(questions)}] {ms:>5}ms  {rewritten[len(q.question):][:90]}", flush=True)
print(f"done: {len(cache['queries'])} rewrites cached -> {OUT}")
