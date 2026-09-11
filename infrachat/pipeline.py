"""The query pipeline — every seam composed, and nothing else.

This function is the project's load-bearing claim. Phases 2-4 add a cross-encoder, a BM25
arm and a query rewriter, and **none of them edit this file**: they swap an implementation
behind an existing seam (ADR-0002). If a future phase needs a line here, the seam was
wrong — fix the seam, not the pipeline.

The two gates are the only places a query can stop, and both live here rather than inside
a component, so the refusal logic cannot be bypassed by swapping a component out.
"""

from __future__ import annotations

from dataclasses import dataclass

from infrachat.answer import citations
from infrachat.answer.gate import GateDecision, check
from infrachat.answer.llm import LLMClient
from infrachat.answer.prompt import SYSTEM_PROMPT, build_prompt, offered_tags
from infrachat.config import Config
from infrachat.models import Answer, Retrieved
from infrachat.retrieve.dense import Retriever
from infrachat.retrieve.rerank import Reranker
from infrachat.retrieve.rewrite import QueryRewriter


@dataclass
class Deps:
    """The swappable parts. Phase 1 passes null objects for rewriter and reranker."""

    rewriter: QueryRewriter
    retriever: Retriever
    reranker: Reranker
    llm: LLMClient | None = None      # absent is legal: --retrieval-only needs no key


@dataclass
class Retrieval:
    """What retrieval produced, before the LLM is involved.

    Returned on its own so `ask --retrieval-only` can show exactly what the gate saw —
    the debugging surface that stands in for a test suite.
    """

    query: str          # after rewriting
    hits: list[Retrieved]
    decision: GateDecision


def retrieve(query: str, cfg: Config, deps: Deps) -> Retrieval:
    """Rewrite → retrieve → rerank → gate. No LLM, no API key."""
    q = deps.rewriter.rewrite(query)
    candidates = deps.retriever.retrieve(q, cfg.retrieval.retrieve_n)
    hits = deps.reranker.rerank(q, candidates, cfg.retrieval.k)
    return Retrieval(query=q, hits=hits, decision=check(hits, cfg.retrieval.floor))


def answer_query(query: str, cfg: Config, deps: Deps) -> Answer:
    """A cited answer, or one of the two refusals."""
    return answer_from(retrieve(query, cfg, deps), cfg, deps)


def answer_from(r: Retrieval, cfg: Config, deps: Deps) -> Answer:
    """The generation half, given a Retrieval the caller already has.

    Exists so a caller that needs to *show* the retrieval — the UI's evidence panel, the
    eval harness's per-question metrics — does not retrieve twice. The alternative was
    letting those callers read the gate decision to decide whether to call the LLM, which
    would put gate logic outside this file; the gates live here so swapping a component
    cannot bypass them.
    """
    if not r.decision.passed:                                    # gate 1 — F8
        return Answer.refuse(cfg.refusal_message())

    if deps.llm is None:
        raise RuntimeError("no generator configured — see config.yaml `llm:`")

    max_chunks = cfg.require_llm().max_context_chunks
    completion = deps.llm.complete(
        SYSTEM_PROMPT, build_prompt(r.query, r.decision.hits, max_chunks)
    )
    return citations.verify(                                     # gate 2 — F9
        completion, r.decision.hits, offered_tags(r.decision.hits, max_chunks)
    )
