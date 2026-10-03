"""F17 — the HTTP API: the traced pipeline, streamed as Server-Sent Events.

The UI is a static site on GitHub Pages (web/); this is the only thing it talks to. It
does exactly one interesting thing — run `trace.answer` and forward its events — so every
refusal, every gate verdict and every citation a browser sees is the same one `ask --trace`
prints and the eval scores (docs/DEMO-PLAN.md § 3).

    infrachat serve -c config.yaml            # http://localhost:8000

Threading: the pipeline is synchronous and SQLite connections are bound to the thread that
opened them, so questions run on a small pool where **each worker owns its own read-only
connection and retriever**. The heavy, thread-safe parts — the ONNX embedder, the
reranker, the HTTP client to the LLM — are built once and shared.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from litestar import Litestar, get, post
from litestar.config.cors import CORSConfig
from litestar.exceptions import HTTPException, ValidationException
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.response import ServerSentEvent
from msgspec import Struct

from infrachat import embed, trace
from infrachat.answer.llm import OpenAICompatClient
from infrachat.config import Config, load_config
from infrachat.evaluate import _is_daily_cap
from infrachat.pipeline import Deps
from infrachat.retrieve.dense import DenseRetriever
from infrachat.retrieve.hybrid import HybridRetriever
from infrachat.retrieve.rerank import build as build_reranker
from infrachat.retrieve.rewrite import build as build_rewriter
from infrachat.store.chunks import ChunkStore

MAX_QUESTION_CHARS = 500
WORKERS = 4

#: The Pages site and the local dev server. Override with a comma-separated
#: INFRACHAT_CORS_ORIGINS; the API holds the LLM key, so it answers no one else's pages.
DEFAULT_ORIGINS = "https://adssib.github.io,http://localhost:5173"


class AskBody(Struct):
    question: str


class Engine:
    """Everything a question needs, built once at startup."""

    def __init__(self, config_path: Path) -> None:
        self.cfg: Config = load_config(config_path)
        root = config_path.resolve().parent
        self.db_path = self.cfg.db_path if self.cfg.db_path.is_absolute() else root / self.cfg.db_path
        if not self.db_path.exists():
            raise SystemExit(f"no index at {self.db_path} — build it with `infrachat ingest`")
        self.embedder = embed.build(self.cfg.embedder.model)
        self.reranker = build_reranker(self.cfg.rerank)
        llm_cfg = self.cfg.require_llm()
        # Two retries, not the eval's six: a person is waiting, and a minute of silent
        # backoff on a daily cap is worse than an honest "come back later".
        self.llm = OpenAICompatClient(llm_cfg.base_url, llm_cfg.model, llm_cfg.api_key_env,
                                      max_tokens=llm_cfg.max_tokens, max_retries=2)
        self.rewriter = build_rewriter(self.cfg.rewrite, llm_cfg if self.cfg.rewrite.enabled else None)
        self._local = threading.local()
        self.pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="ask")
        self.ready = False

    def warm(self) -> None:
        """Load the model and open the index before the first visitor pays for it."""
        self.embedder.embed_query("warm up")
        self.deps()
        self.ready = True

    def deps(self) -> Deps:
        """This thread's pipeline: its own connection and retriever, the shared rest."""
        local = self._local
        if not hasattr(local, "deps"):
            store = ChunkStore(self.db_path, dim=self.embedder.dim)
            retriever = (HybridRetriever(store, self.embedder) if self.cfg.retrieval.hybrid.enabled
                         else DenseRetriever(store, self.embedder))
            local.deps = Deps(rewriter=self.rewriter, retriever=retriever,
                              reranker=self.reranker, llm=self.llm)
        return local.deps


def _error_event(exc: BaseException) -> dict:
    if _is_daily_cap(exc):
        return {"kind": "daily_cap", "message": "The free LLM tier has used today's token budget. "
                "Recorded answers still work; live answers come back when it resets."}
    if "rate limited" in str(exc):
        return {"kind": "rate_limit", "message": "Too many questions this minute. Wait a few seconds and ask again."}
    return {"kind": "internal", "message": "Something went wrong answering that. Try again, or ask something else."}


def create_app(config_path: Path) -> Litestar:
    engine = Engine(config_path)

    @post("/api/ask")
    async def ask(data: AskBody) -> ServerSentEvent:
        question = data.question.strip()
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise ValidationException(f"a question is 1 to {MAX_QUESTION_CHARS} characters")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def put(item: dict | None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def work() -> None:
            try:
                trace.answer(question, engine.cfg, engine.deps(),
                             lambda e: put({"event": e.type, "data": json.dumps(e.data)}))
            except Exception as exc:  # reported to the browser as an event, not a 500 mid-stream
                put({"event": "error", "data": json.dumps(_error_event(exc))})
            finally:
                put(None)

        loop.run_in_executor(engine.pool, work)

        async def stream() -> AsyncIterator[dict]:
            while (item := await queue.get()) is not None:
                yield item

        # X-Accel-Buffering: off for any proxy that would otherwise hold the stream back.
        return ServerSentEvent(stream(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @get("/api/meta")
    async def meta() -> dict[str, Any]:
        cfg = engine.cfg
        return {
            "expires_at": os.environ.get("EXPIRES_AT"),
            "commit": os.environ.get("GIT_SHA"),
            "index": os.environ.get("INDEX_VERSION"),
            "config": {"hybrid": cfg.retrieval.hybrid.enabled, "rerank": cfg.rerank.enabled,
                       "rewrite": cfg.rewrite.enabled, "floor": cfg.retrieval.floor,
                       "model": cfg.require_llm().model},
            "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @get("/healthz")
    async def healthz() -> dict[str, str]:
        if not engine.ready:
            raise HTTPException(status_code=503, detail="warming up")
        return {"status": "ok"}

    origins = os.environ.get("INFRACHAT_CORS_ORIGINS", DEFAULT_ORIGINS).split(",")
    rate_limit = RateLimitConfig(rate_limit=("minute", 10), exclude=["/healthz", "/api/meta"])

    async def warm_in_background() -> None:
        await asyncio.get_running_loop().run_in_executor(engine.pool, engine.warm)

    return Litestar(
        route_handlers=[ask, meta, healthz],
        cors_config=CORSConfig(allow_origins=[o.strip() for o in origins if o.strip()],
                               allow_methods=["GET", "POST"], allow_headers=["content-type"]),
        middleware=[rate_limit.middleware],
        on_startup=[warm_in_background],
    )


def run(config_path: Path, host: str, port: int) -> None:
    import uvicorn

    # proxy_headers: behind Azure's ingress every request arrives from the proxy, so the
    # rate limit must key on X-Forwarded-For or it becomes one limit for everyone.
    uvicorn.run(create_app(config_path), host=host, port=port,
                proxy_headers=True, forwarded_allow_ips="*", log_level="info")
