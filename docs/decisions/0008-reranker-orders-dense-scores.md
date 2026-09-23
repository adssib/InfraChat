# ADR-0008: The reranker decides order; the dense retriever still decides score

- **Status:** Accepted
- **Date:** 2026-09-22
- **Phase:** 2

## Context

A cross-encoder scores a (query, chunk) pair jointly, and its output is on a completely
different scale from cosine similarity. Measured over the 1,740 query/chunk pairs this
eval set produces, `ms-marco-MiniLM-L-6-v2` logits span **−11.43 to +9.57**, and their
sigmoid is near-bimodal: 46.8% of pairs below 0.1, 25.7% above 0.9, only 27.5% between.

`Retrieved.score` is not a display value. It is what the grounding gate compares against
`retrieval.floor` (F8), and `floor` is **0.65 — derived in `eval/floor-tuning.md` as
`min(answerable top-1) − 1 SD` of the *dense cosine* distribution.** It encodes a
calibration against one specific score distribution, not a generic "how good is this"
number.

So enabling the reranker forces a choice about what goes in that field, and the wrong
choice contaminates the one measurement Phase 2 exists to produce.

## Decision

**The cross-encoder decides the order. `Retrieved.score` keeps the dense cosine
similarity.** Reranking reorders the candidate list and truncates to `k`; it does not
rewrite the number the gate reads.

## Alternatives considered

- **Write `sigmoid(logit)` into `score`.** In [0,1], so it satisfies the SPEC's range, and
  superficially the "more accurate" relevance estimate. Measured against an unchanged
  `floor=0.65`, it moves the gate from **1/66 to 8/66 answerable questions refused**, and
  from 2/21 to 8/21 should-refuse caught at gate 1. Part of that reads as an improvement —
  which is exactly the trap. The Phase 2 row would then be reporting reranking **plus a
  silently re-tuned refusal threshold**, and no amount of care downstream could separate
  them. Top-1 standard deviation also jumps from 0.053 (dense) to 0.242, so `floor` would
  need re-deriving before the number meant anything.
- **Write the raw logit.** Rejected outright: not in [0,1], which `docs/SPEC.md` pins, and
  a threshold of 0.65 on a ±11 scale passes anything the model does not actively dislike.
- **Re-derive `floor` for the cross-encoder distribution and use sigmoid.** Defensible, and
  possibly right eventually — but it changes two variables in the phase where exactly one
  should change. If it happens, it is its own ADR with its own measurement.

## Consequences

- ✅ **The Phase 2 delta measures reranking alone.** Baseline and `+reranker` differ by one
  object; the gate sees the same kind of number in both arms.
- ✅ `floor` keeps the meaning `eval/floor-tuning.md` derived for it, and the sweep in that
  document stays valid.
- ⚠️ **Enabling the reranker can only make gate 1 stricter, never looser.** The gate reads
  `hits[0].score`; the chunk the cross-encoder promotes has a cosine no higher than the
  dense top-1 it displaced. Pass→refuse is possible, refuse→pass is not.
- ⚠️ That bites **once in 87 questions**, and instructively. *"My image is 1.5GB. How do I
  shrink it?"* improves from RR 0.500 to **1.000** — the cross-encoder correctly promotes
  `building/best-practices.md` over an SLSA provenance page — but that chunk's cosine is
  0.639 against the displaced 0.722, so it misses the 0.65 floor by **0.011**. A better
  answer, refused. One question, and `eval/floor-tuning.md` predicted exactly this class of
  failure before the reranker existed.
- ⚠️ **The discarded signal is real.** A cross-encoder's judgement is better than cosine at
  deciding relevance; this decision throws it away for gating purposes. `scored()` is left
  public so the logits stay inspectable for a future calibration.
- 🔭 Revisit when Phase 3 fusion lands: RRF produces a *third* scale, and at that point
  `hits[0].score` is no longer a cosine at all. The rule in `eval/floor-tuning.md` —
  pre-register the procedure, not the value — is what should be re-run, not this decision
  re-argued.
