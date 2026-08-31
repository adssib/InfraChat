# ADR-0002: Every optional component is a config-toggled null object

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 (foundational)

## Context

The project's entire premise is *"add one retrieval component, measure the delta."* That only
produces trustworthy numbers if the baseline and the enhanced system differ by **exactly one
thing**. The obvious way to build it — ship the baseline, then add the reranker into the pipeline
in Phase 2 — quietly breaks that: the Phase 2 code path is not the Phase 1 code path, so the delta
measures "reranking plus whatever else the refactor changed."

There's a second force. Three components are planned (reranker, hybrid, rewriter) and each could
be added, removed, or reordered. Rewiring the pipeline three times is three chances to change
behaviour by accident.

## Decision

**Every optional seam exists from Phase 1, wired to a null object, and is toggled by config.**

- Phase 1 runs an identity `QueryRewriter` (returns the query unchanged), a dense-only
  `Retriever`, and a pass-through `Reranker` (returns hits unchanged).
- Later phases **swap one implementation** behind an unchanged interface. The pipeline function
  is never edited.
- The switch is a config key — `rerank.enabled`, `hybrid.enabled`, `rewrite.enabled`. **The config
  is the experiment**; each eval run pins one.

## Alternatives considered

- **Add components to the pipeline as each phase lands** — less code up front, but the baseline
  and enhanced runs execute different code, so a measured delta can't be attributed cleanly. It
  also makes "turn it back off" a revert rather than a flag.
- **Branch per phase** (`phase-2-reranker` etc.) — clean isolation, but the phases can't be
  compared in a single run, and the final system would need a merge of four divergent pipelines.
- **`if enabled:` conditionals inline in the pipeline** — no extra classes, but the pipeline
  accumulates branches, and each branch is a place for the two paths to drift apart.

## Consequences

- ✅ **A/B comparisons are clean**: same code path, one seam changed, everything else identical.
- ✅ Turning a component **off again is a config edit**, so a negative result can be acted on
  immediately — which matters because reporting one is an explicit goal.
- ✅ Implementations are swappable beyond the roadmap: Chroma → pgvector, local → hosted embedder.
- ⚠️ **Interfaces must be designed before their implementations exist**, which risks guessing
  wrong. Mitigated by keeping them minimal — one method each, shapes fixed in
  [SPEC.md](../SPEC.md#the-seams-pluggable-interfaces).
- ⚠️ Null objects are **invisible cost**: a pass-through `Reranker` still allocates and copies.
  Negligible here, and worth naming.
- ⚠️ A seam is only honest if it's **actually swappable**. If the hybrid retriever ends up needing
  the pipeline to know about it, this ADR has failed and should be superseded rather than fudged.
- 🔭 Revisit if a planned component genuinely cannot fit an existing seam — that's a signal the
  seam is wrong, and the fix is a new ADR redesigning it.
