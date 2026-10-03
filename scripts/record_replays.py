"""Record real traced runs of the UI's example questions, for offline replay.

    ./.venv/bin/python scripts/record_replays.py

Each example is run through `trace.answer` — the same narration the live API streams —
and every event is saved with the milliseconds since the question was asked. The web
UI replays these at their real pace when no backend session is running, so offline mode
shows what the system actually did, not a mock-up (docs/DEMO-PLAN.md § 1).

Writes web/public/replays/<slug>.json and web/public/replays/index.json. Costs one LLM
call per example that clears gate 1. Re-record when the corpus, config or prompt change:
a replay is a recording of one configuration.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from infrachat import trace  # noqa: E402
from infrachat.cli import _build_deps, _open_index  # noqa: E402
from infrachat.config import load_config  # noqa: E402

OUT = ROOT / "web" / "public" / "replays"
EXAMPLES = ROOT / "web" / "src" / "examples.json"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main() -> None:
    groups = json.loads(EXAMPLES.read_text())
    cfg = load_config(ROOT / "config.yaml")
    store, embedder = _open_index(cfg, ROOT)
    deps = _build_deps(cfg, store, embedder, with_llm=True)
    embedder.embed_query("warm up")   # the first embed loads the model; don't record that
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    try:
        for group in groups:
            for q in group["questions"]:
                events: list[dict] = []
                t0 = time.perf_counter()
                trace.answer(q, cfg, deps, lambda e: events.append(
                    {"t": round((time.perf_counter() - t0) * 1000), "type": e.type, "data": e.data}))
                name = slug(q)
                (OUT / f"{name}.json").write_text(json.dumps(
                    {"question": q, "recorded": time.strftime("%Y-%m-%d"), "events": events}))
                index[q] = f"{name}.json"
                outcome = next(e["type"] for e in reversed(events) if e["type"] in ("answer", "refusal"))
                print(f"  {outcome:<8} {events[-1]['t']:>6} ms  {q}")
                time.sleep(3)   # stay well inside Groq's per-minute token budget
    finally:
        store.close()
    (OUT / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
