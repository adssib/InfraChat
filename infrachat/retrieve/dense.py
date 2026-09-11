"""F6 — dense retrieval: question → ranked candidate chunks.

This is where a store distance becomes the **score the grounding gate reads**, so it is
the one place that decides what `retrieval.floor` means. The store deliberately does not
do this conversion: keeping it here means swapping the vector backend cannot silently
move the refusal threshold.
"""

from __future__ import annotations

from typing import Protocol

from infrachat.embed import Embedder
from infrachat.models import Retrieved
from infrachat.store.chunks import ChunkStore


class Retriever(Protocol):
    """The seam. Dense in Phase 1; a hybrid implementation fuses arms in Phase 3."""

    def retrieve(self, query: str, k: int) -> list[Retrieved]: ...


def _score(distance: float) -> float:
    """Cosine distance → cosine similarity in [0, 1].

    The store's `vec_chunks` table declares `distance_metric=cosine`, so distance is
    `1 - cos`. Clamped because float error can put an identical vector a hair below zero
    or above one, and a score outside [0,1] would make the floor comparison nonsense.
    """
    return max(0.0, min(1.0, 1.0 - distance))


class DenseRetriever:
    """Embed the query, take the nearest neighbours, hand back scored chunks."""

    def __init__(self, store: ChunkStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def retrieve(self, query: str, k: int) -> list[Retrieved]:
        # embed_query, not embed_documents — bge encodes questions differently, and
        # using the passage encoder here degrades recall without raising anything.
        vector = self.embedder.embed_query(query)
        hits = self.store.search(vector, k)
        return [Retrieved(chunk=chunk, score=_score(distance)) for chunk, distance in hits]
