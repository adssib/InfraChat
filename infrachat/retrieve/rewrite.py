"""F14 — the query-rewriter seam, with its Phase 1 null object."""

from __future__ import annotations

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
