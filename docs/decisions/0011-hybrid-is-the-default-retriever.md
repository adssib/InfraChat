# ADR-0011: Hybrid retrieval is the default; the reranker is available but off

- **Status:** Accepted
- **Date:** 2026-09-24
- **Phase:** 3 (closes the question ADR-0009 left open)

## Context

ADR-0009 found hybrid search (BM25 + dense, fused by reciprocal rank) buys 71% of the
reranker's MRR gain at 0.8% of its latency, and left one question open: does it also
avoid the reranker's cost to refusal recall? Phase 2 had measured that cost — two
near-miss refusals became fabrications with valid citations, built from chunks the
cross-encoder promoted to #1.

The generative hybrid-only run answered it. Paired, all 87 questions (86 against the
baseline, which has one errored row):

| metric | baseline | +reranker | +hybrid |
|---|---|---|---|
| MRR | 0.795 | **0.867** | 0.858 / 0.845* |
| refusal recall | 0.952 | 0.857 | **0.952** |
| refusal precision | 0.833 | 0.857 | **0.909** |
| false-refusal rate | 0.062 | 0.045 | **0.031** |
| citation validity | 1.000 | 0.985 | **1.000** |
| added retrieval latency | — | +821 ms | **+6 ms** |

\*0.858 paired with the baseline (86 questions), 0.845 paired with the reranker (87).

## Decision

**`retrieval.hybrid.enabled: true`, `rerank.enabled: false`** is the shipped
configuration. The reranker stays in the codebase, selectable by config, for a use
where ranking matters more than refusal.

## Alternatives considered

- **Reranker as default.** Best MRR by about 0.02 — roughly one question. Costs 0.095
  refusal recall (two fabrications) and ~800 ms per query. By ADR-0001's ordering, a
  confident wrong answer is worse than a refusal, so this trade runs the wrong way.
- **Reranker + hybrid.** Measured redundant in ADR-0009 (MRR 0.862, below the reranker
  alone) and inherits the reranker's refusal cost.
- **Baseline (dense only).** Strictly dominated: hybrid matches its refusal recall, halves
  its false refusals, and adds 0.063 MRR.

## Consequences

- ✅ Better ranking than the baseline with **no** loss of refusal recall — the only
  addition in four phases that improved retrieval without costing refusal.
- ✅ The public demo gets a retriever that adds 6 ms, not 800.
- ⚠️ Source accuracy dips 0.984 → 0.968 against the baseline (one question citing the
  other doc set). Worth watching; not decision-changing at n=1.
- ⚠️ The mechanism is a hypothesis, not a proof: rank fusion cannot single out the most
  plausible chunk the way a cross-encoder can, and that selection is what turned
  near-misses into answers. n=2 fabrications on a non-deterministic provider.
- ⚠️ p50 latencies in these runs are not comparable to each other — each generative run was
  completed over hours by `--resume` under different provider load. Retrieval latency
  (+6 ms vs +821 ms) was measured in-process and is.
- 🔭 Revisit if the entailment gate (ADR-0007) lands: once fabrications with valid
  citations are caught downstream, the reranker's refusal cost may disappear and its MRR
  advantage becomes free.
