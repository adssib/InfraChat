"""F13 — hybrid retrieval: a dense arm and a BM25 arm, fused by reciprocal rank.

Same `Retriever` seam as `DenseRetriever` — the pipeline cannot tell them apart, which is
what makes Phase 3 an A/B rather than a rewrite (ADR-0002).

Dense embeddings match *meaning* and are weak on *literals*: an identifier such as
BUILDKIT_INLINE_CACHE appears in exactly one chunk of 4,908, and dense retrieval ranks a
generic cache page above it. BM25 is the reverse. Reciprocal rank fusion combines the two
**by rank, not by score** — `1 / (k + rank)` summed across arms — so the arms never need
a shared scale, and a document ranked highly by either arm rises.

**Fusion decides order; `Retrieved.score` stays the dense cosine** (ADR-0009, extending
ADR-0008). A chunk found only by BM25 has no dense score of its own, so its cosine is
looked up by id. That keeps `retrieval.floor` meaning exactly what eval/floor-tuning.md
derived, instead of introducing a third score scale the gate was never calibrated for.
"""

from __future__ import annotations

import time

from infrachat.embed import Embedder
from infrachat.models import Retrieved
from infrachat.retrieve.dense import _score
from infrachat.store.chunks import ChunkStore

#: The conventional RRF constant (Cormack et al., 2009). It damps the difference between
#: rank 1 and rank 2 so one arm's top hit cannot dominate on its own. Fixed rather than
#: tuned: tuning it on the eval set would be the circularity eval/floor-tuning.md warns of.
RRF_K = 60


class HybridRetriever:
    """Dense top-n and BM25 top-n, fused by reciprocal rank, scored by cosine."""

    def __init__(self, store: ChunkStore, embedder: Embedder, *, rrf_k: int = RRF_K) -> None:
        self.store = store
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.store.ensure_keyword_index()

    def retrieve(self, query: str, k: int) -> list[Retrieved]:
        return self.retrieve_explained(query, k)[0]

    def retrieve_explained(self, query: str, k: int) -> tuple[list[Retrieved], dict]:
        """`retrieve`, plus what each arm returned — for the trace, never for a decision.

        Returned rather than stored on `self`: one retriever serves concurrent requests in
        the API, so an attribute would hand one request another's arms.
        """
        t0 = time.perf_counter()
        vector = self.embedder.embed_query(query)
        t1 = time.perf_counter()
        dense = self.store.search(vector, k)                  # [(Chunk, cosine distance)]
        t2 = time.perf_counter()
        keyword = self.store.keyword_search(query, k)         # [chunk_id], best first
        t3 = time.perf_counter()

        fused: dict[str, float] = {}
        for rank, (chunk, _) in enumerate(dense, 1):
            fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (self.rrf_k + rank)
        for rank, chunk_id in enumerate(keyword, 1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.rrf_k + rank)

        # sorted() is stable and dense ids were inserted first, so ties keep dense order.
        order = sorted(fused, key=fused.__getitem__, reverse=True)[:k]

        chunks = {c.id: c for c, _ in dense}
        distances = {c.id: d for c, d in dense}
        keyword_only = [i for i in order if i not in chunks]
        for c in self.store.hydrate(keyword_only):
            chunks[c.id] = c
        distances.update(self.store.cosine_distances(vector, keyword_only))

        hits = [Retrieved(chunk=chunks[i], score=_score(distances[i]))
                for i in order if i in chunks and i in distances]
        arms = {
            "dense": [c.id for c, _ in dense],
            "keyword": list(keyword),
            "ms": {"embed": (t1 - t0) * 1000, "dense": (t2 - t1) * 1000,
                   "keyword": (t3 - t2) * 1000},
        }
        return hits, arms
