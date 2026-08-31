# ADR-0003: Build the eval harness in Phase 1, before any optional component

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 (the spine)

## Context

The natural build order is: get it working, then measure it. It's more satisfying, and measurement
feels like something you can bolt on later.

But this project's claim is comparative — *"reranking improved retrieval hit-rate by X"* — and
that claim needs a **baseline measured on the same question set, before the reranker existed**.
A baseline cannot be reconstructed after the fact: once the pipeline has changed, the only honest
way back is to revert, re-run, and hope nothing else moved.

There is also a subtler force. Writing the question set forces decisions that are otherwise
deferred until they're expensive: what counts as a correct citation, what "should refuse" means
in practice, which questions are hard on purpose.

## Decision

**The eval harness ships in Phase 1**, alongside the baseline pipeline and before any optional
component. It runs a fixed question set (k8s-answerable / docker-answerable / should-refuse) and
prints scores tagged with a `run_label`. Phase 1's run *is* the baseline every later phase is
measured against.

## Alternatives considered

- **Add eval in Phase 5, before the write-up** — by then the baseline is gone. Every earlier
  "improvement" would have to be re-measured by reverting the code, and any that couldn't be
  cleanly reverted would just be asserted.
- **Eyeball a handful of questions each phase** — fast, and exactly the vibe-based evaluation the
  project exists to avoid. It also can't detect a regression in a class you didn't happen to try.
- **Use an off-the-shelf RAG eval framework** — more metrics for free, but a heavy dependency for
  a fixed question set, and the metric definitions become someone else's opinion rather than a
  thing to reason about. The metrics here are simple enough to own.

## Consequences

- ✅ **Every later phase has a real baseline to beat**, measured on identical inputs.
- ✅ Writing the question set early **surfaces design questions cheaply** — citation format,
  refusal semantics, which failures matter — while they're still easy to change.
- ✅ A regression in a class you weren't thinking about gets caught, because every class runs
  every time.
- ⚠️ **Phase 1 is bigger.** The baseline isn't done when it answers a question; it's done when it
  can score itself. Accepted: it's the single highest-leverage thing in the project.
- ⚠️ **The question set becomes a fixed asset.** Adding questions later invalidates comparison
  with earlier runs — so new questions only land at a phase boundary, followed by a baseline re-run.
- ⚠️ A small hand-written set means **small deltas are noise**. Mitigated by reporting the
  question count next to every number ([EVAL.md](../EVAL.md)).
- 🔭 Revisit the *metrics* (not the timing) if hit-rate and MRR stop discriminating between
  phases — e.g. add nDCG, or per-class breakdowns as the primary view.
