"""F14 — the query-rewriter seam, with its Phase 1 null object."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class QueryRewriter(Protocol):
    def rewrite(self, query: str) -> str: ...


class IdentityRewriter:
    """Return the question unchanged — the Phase 1 baseline.

    Deliberately a real object rather than an `if cfg.rewrite.enabled` branch in the
    pipeline: a branch accumulates, an object swaps.
    """

    def rewrite(self, query: str) -> str:
        return query


_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "rewrite.txt"
REWRITE_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
REWRITE_PROMPT_SHA = hashlib.sha256(REWRITE_PROMPT.encode("utf-8")).hexdigest()[:12]


class LLMRewriter:
    """F14 — expand the question with the documentation's own vocabulary. Phase 4.

    **Appends, never replaces.** The retriever sees `question + terms`. A rewrite that
    replaces the question drifts: measured, the model turned "how do I make my docker
    image smaller?" into "docker image size reduction techniques", which loses the user's
    wording and still never says "multi-stage". Appending keeps the meaning and widens the
    vocabulary. The generator always answers the ORIGINAL question (pipeline.Retrieval
    .question); this output only steers retrieval.

    A failed rewrite raises rather than falling back to the identity rewriter: a silent
    fallback would mix two experimental conditions in one run.
    """

    def __init__(self, client) -> None:
        self.client = client

    def rewrite(self, query: str) -> str:
        raw = self.client.complete(REWRITE_PROMPT, query)
        terms = " ".join(raw.split())[:300]       # one line, bounded
        return f"{query} {terms}".strip() if terms else query


def build(rewrite_cfg, llm_cfg) -> QueryRewriter:
    """Identity when disabled; otherwise an LLM rewriter on the generator's endpoint."""
    if not rewrite_cfg.enabled:
        return IdentityRewriter()
    from infrachat.answer.llm import OpenAICompatClient

    return LLMRewriter(OpenAICompatClient(
        base_url=llm_cfg.base_url,
        model=rewrite_cfg.model,
        api_key_env=llm_cfg.api_key_env,
        max_tokens=rewrite_cfg.max_tokens,
        reasoning_effort=rewrite_cfg.reasoning_effort,
    ))
