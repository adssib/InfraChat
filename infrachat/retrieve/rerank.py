"""F12 — the reranker seam, with its Phase 1 null object.

The pass-through is not a placeholder to be replaced by "the real code" — it is the
baseline arm of the experiment. Phase 1 and Phase 2 run the *same* pipeline; only this
object differs. That is what makes the A/B honest (ADR-0002).
"""

from __future__ import annotations

from typing import Protocol

from infrachat.models import Retrieved


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]: ...


class PassthroughReranker:
    """Keep the retriever's order, keep the top `top_k`. The Phase 1 baseline.

    Note it still truncates: `retrieve_n` candidates come in, `k` go to the gate. Without
    that, the baseline would send 20 chunks to the LLM and Phase 2's improvement would be
    confounded with sending fewer.
    """

    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]:
        return hits[:top_k]
