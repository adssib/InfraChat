# ADR-0009: Hybrid fusion keeps the cosine score, and substitutes for the reranker rather than stacking on it

- **Status:** Accepted
- **Date:** 2026-09-23
- **Phase:** 3

## Context

Phase 3 adds a BM25 keyword arm (SQLite FTS5) and fuses it with dense retrieval by
reciprocal rank. Two decisions follow, and the second one could only be made by measuring.

**1. What goes in `Retrieved.score`.** The roadmap expected fusion to introduce "a third
score scale" the grounding gate was never calibrated for. A chunk found only by BM25 has no
dense score, and an RRF score (`Σ 1/(60 + rank)`) lives around 0.01–0.03 — a threshold of
0.65 on that scale would refuse everything.

**2. Whether hybrid ships, and on top of what.** The phases are cumulative by design, so
"Phase 3" was assumed to mean reranker **plus** hybrid. The Phase 1 baseline had already
warned that exact-term retrieval — the slice BM25 exists to win — started at 0.833, and the
Phase 2 reranker lifted it to 0.919 before any keyword index existed.

## Decision

**Fusion decides order; `Retrieved.score` stays the dense cosine.** A BM25-only hit gets
its cosine looked up by id (`vec_distance_cosine` over `vec_chunks`). This extends
ADR-0008's rule — *a component may reorder, it may not rescale* — to every stage before the
gate, so `retrieval.floor` keeps the meaning `eval/floor-tuning.md` derived for it.

**Hybrid is a substitute for the reranker, not an addition to it.** Measured on all 87
questions, retrieval only:

| arm | MRR | exact-term MRR | hit@5 | added p50 latency |
|---|---|---|---|---|
| dense | 0.788 | 0.833 | 0.970 | — |
| **+hybrid** | **0.845** | **0.914** | 0.955 | **+6 ms** |
| +reranker | 0.867 | 0.919 | 0.985 | +821 ms |
| +reranker +hybrid | 0.862 | 0.917 | 0.970 | +827 ms |

Hybrid alone buys **71% of the reranker's MRR gain at 0.8% of its added latency.** Stacked
on the reranker it is redundant and slightly harmful: 1 question improves, 5 regress. RRF
pulls BM25 hits into the 20-candidate pool, displacing dense candidates the cross-encoder
would have promoted — and the cross-encoder already recovers the literal matches BM25
exists to find.

## Alternatives considered

- **Put the RRF score in `Retrieved.score`.** Rejected: a different scale on every phase
  would make the Phase 3 row measure fusion *plus* a re-tuned gate. Same argument as
  ADR-0008, one stage earlier.
- **Min-max normalise and blend BM25 with cosine.** Needs a weight, and tuning a weight on
  the eval set is the circularity `eval/floor-tuning.md` measured at 4.4 points of
  optimism. RRF has one conventional constant (k = 60) and it is not tuned here.
- **Ship reranker + hybrid because the plan said the phases stack.** Rejected by the
  measurement: MRR 0.867 → 0.862, hit@5 0.985 → 0.970, for extra latency.

## Consequences

- ✅ The gate sees the same kind of number in every phase so far; one `floor` serves all.
- ✅ A second viable configuration exists: **hybrid-only** for latency-sensitive serving
  (the public demo), **reranker** where ranking quality matters most.
- ✅ The Phase 1 baseline's prediction held — exact-term headroom was mostly gone — and the
  negative result is recorded rather than tuned away. `ROADMAP.md` says a measured negative
  is a strong thing to report; this is one.
- ⚠️ Like the reranker, fusion can only make gate 1 **stricter**: the fused #1 has a cosine
  no higher than the dense #1. With both on, answerable questions refused at gate 1 go
  1 → 3 and refusals caught go 2 → 4 — a floor trade, not a free win.
- ⚠️ BM25 alone costs hit@5 (0.970 → 0.955): it can push the one correct chunk out of a
  top-20 pool that dense retrieval had it in.
- 🔭 Open, and being measured: whether hybrid-only avoids the refusal-recall cost the
  reranker showed in Phase 2 (0.952 → 0.857, two near-miss refusals turned into
  fabrications built from reranker-promoted chunks). If it does, hybrid-only is the better
  default on both axes that matter here.
