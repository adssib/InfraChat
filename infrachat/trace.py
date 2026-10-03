"""The pipeline, narrated — every step as an event, for the UI's live trace.

`pipeline.py` is never edited (CLAUDE.md invariant 2), so the narration comes from the
seams instead: each dependency is wrapped in a decorator that runs the real component
and emits what it did. The gates are not re-implemented here — their verdicts are read
from what the pipeline returned (`Retrieval.decision`, the `Answer`), so this module can
report a refusal but can never cause or prevent one.

The event names and payloads are the contract in docs/DEMO-PLAN.md § Events. Every
event is a plain JSON-serialisable dict, so the CLI prints them and the API streams them
without either knowing what is inside.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from infrachat import pipeline
from infrachat.answer import citations
from infrachat.answer.prompt import offered_tags
from infrachat.config import Config
from infrachat.models import Answer, Retrieved
from infrachat.pipeline import Deps
from infrachat.retrieve.rerank import PassthroughReranker


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


Emit = Callable[[Event], None]


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _hit(rank: int, r: Retrieved) -> dict:
    c = r.chunk
    return {"rank": rank, "tag": c.tag, "chunk_id": c.id, "source": c.source,
            "doc": c.source_doc, "lines": c.source_location, "score": round(r.score, 4)}


class TracedRewriter:
    def __init__(self, inner, emit: Emit) -> None:
        self.inner, self.emit = inner, emit

    def rewrite(self, query: str) -> str:
        t0 = time.perf_counter()
        out = self.inner.rewrite(query)
        self.emit(Event("rewrite", {"query": out, "changed": out != query, "ms": _ms(t0)}))
        return out


class TracedRetriever:
    """Emits the dense and keyword arms separately when the retriever can explain itself
    (hybrid), and the dense list alone when it can't (dense-only)."""

    def __init__(self, inner, emit: Emit) -> None:
        self.inner, self.emit = inner, emit

    def retrieve(self, query: str, k: int) -> list[Retrieved]:
        t0 = time.perf_counter()
        if not hasattr(self.inner, "retrieve_explained"):
            hits = self.inner.retrieve(query, k)
            self.emit(Event("retrieve.dense", {"hits": [_hit(i, h) for i, h in enumerate(hits, 1)],
                                               "ms": _ms(t0)}))
            return hits

        hits, arms = self.inner.retrieve_explained(query, k)
        dense_rank = {cid: i for i, cid in enumerate(arms["dense"], 1)}
        kw_rank = {cid: i for i, cid in enumerate(arms["keyword"], 1)}
        ms = {k_: round(v, 1) for k_, v in arms["ms"].items()}
        self.emit(Event("embed", {"ms": ms["embed"]}))
        self.emit(Event("retrieve.dense", {"count": len(arms["dense"]), "ms": ms["dense"]}))
        self.emit(Event("retrieve.keyword", {"count": len(arms["keyword"]), "ms": ms["keyword"]}))
        self.emit(Event("fuse", {"hits": [
            {**_hit(i, h), "dense_rank": dense_rank.get(h.chunk.id),
             "keyword_rank": kw_rank.get(h.chunk.id)}
            for i, h in enumerate(hits, 1)]}))
        return hits


class TracedReranker:
    def __init__(self, inner, emit: Emit) -> None:
        self.inner, self.emit = inner, emit

    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]:
        t0 = time.perf_counter()
        out = self.inner.rerank(query, hits, top_k)
        before = {h.chunk.id: i for i, h in enumerate(hits, 1)}
        moves = [{"tag": h.chunk.tag, "from": before.get(h.chunk.id), "to": i}
                 for i, h in enumerate(out, 1) if before.get(h.chunk.id) != i]
        self.emit(Event("rerank", {"active": not isinstance(self.inner, PassthroughReranker),
                                   "moves": moves, "ms": _ms(t0),
                                   "hits": [_hit(i, h) for i, h in enumerate(out, 1)]}))
        return out


class TracedLLM:
    """Streams through `inner.stream()` when it has one, so the reasoning and the answer
    tokens reach the caller as they arrive; returns the full text either way, which is
    all the citation gate ever sees."""

    def __init__(self, inner, emit: Emit) -> None:
        self.inner, self.emit = inner, emit
        self.completion: str | None = None
        self.stats: dict = {}

    def complete(self, system: str, user: str) -> str:
        self.emit(Event("prompt", {"tokens_est": (len(system) + len(user)) // 4}))
        t0 = time.perf_counter()
        if hasattr(self.inner, "stream"):
            out = self.inner.stream(
                system, user,
                on_reasoning=lambda d: self.emit(Event("llm.reasoning", {"delta": d})),
                on_token=lambda d: self.emit(Event("llm.token", {"delta": d})),
            )
            self.completion = out.text
            self.stats = {"usage": out.usage, "ratelimit": out.ratelimit}
        else:
            self.completion = self.inner.complete(system, user)
        self.stats["ms"] = _ms(t0)
        return self.completion


def answer(question: str, cfg: Config, deps: Deps, emit: Emit) -> Answer:
    """`pipeline.answer_query`, narrated. Same two calls the pipeline makes, in the same
    order — `retrieve` then `answer_from` — split only so gate 1's verdict can be emitted
    before the LLM is called."""
    t_start = time.perf_counter()
    llm = TracedLLM(deps.llm, emit) if deps.llm is not None else None
    traced = Deps(rewriter=TracedRewriter(deps.rewriter, emit),
                  retriever=TracedRetriever(deps.retriever, emit),
                  reranker=TracedReranker(deps.reranker, emit),
                  llm=llm)
    emit(Event("start", {"question": question, "config": {
        "hybrid": cfg.retrieval.hybrid.enabled, "rerank": cfg.rerank.enabled,
        "rewrite": cfg.rewrite.enabled, "floor": cfg.retrieval.floor}}))

    r = pipeline.retrieve(question, cfg, traced)
    d = r.decision
    emit(Event("gate.floor", {"passed": d.passed, "top_score": d.top_score,
                              "floor": d.floor, "margin": d.margin}))

    result = pipeline.answer_from(r, cfg, traced)

    if not d.passed:
        detail = ("retrieval returned nothing" if d.top_score is None else
                  f"best match {d.top_score:.3f} is below the floor {d.floor}")
        emit(Event("refusal", {"gate": "floor", "reason": result.text, "detail": detail}))
    else:
        completion = llm.completion if llm else ""
        max_chunks = cfg.require_llm().max_context_chunks
        offered = offered_tags(d.hits, max_chunks)
        claimed = citations.parse_tag_candidates(completion or "")
        said_nid = citations._said_not_in_docs(completion or "")
        emit(Event("gate.citations", {
            "passed": result.grounded,
            "cited": [c.tag for c in result.citations],
            "invented": [t for t in claimed if t not in offered],
            "said_not_in_docs": said_nid}))
        if result.grounded:
            emit(Event("answer", {"text": result.text, "citations": [
                {"n": i, "tag": c.tag, "source": c.source, "doc": c.source_doc,
                 "lines": c.source_location} for i, c in enumerate(result.citations, 1)]}))
        else:
            reason = ("the model said the excerpts don't answer it" if said_nid
                      else "the answer cited nothing it was shown")
            emit(Event("refusal", {"gate": "citation", "reason": result.text,
                                   "detail": reason}))

    stats = llm.stats if llm else {}
    emit(Event("done", {"ms_total": _ms(t_start), "llm_ms": stats.get("ms"),
                        "usage": stats.get("usage"), "ratelimit": stats.get("ratelimit")}))
    return result
