# Diagrams

PlantUML sources for every diagram in the docs. Rendered PNGs live in [`../images/`](../images/)
and are committed alongside the sources so the docs render on GitHub without a build step.

| Source | Renders to | Shows |
|---|---|---|
| [`phase1-baseline.puml`](phase1-baseline.puml) | [`phase1-baseline.png`](../images/phase1-baseline.png) | Baseline RAG: ingest → embed → store; dense retrieve → gate → answer, both refusal paths, eval harness |
| [`phase2-reranker.puml`](phase2-reranker.puml) | [`phase2-reranker.png`](../images/phase2-reranker.png) | + cross-encoder reranker (top-20 → rerank → top-5) |
| [`phase3-hybrid.puml`](phase3-hybrid.puml) | [`phase3-hybrid.png`](../images/phase3-hybrid.png) | + BM25 keyword index and RRF fusion |
| [`phase4-query-rewriter.puml`](phase4-query-rewriter.puml) | [`phase4-query-rewriter.png`](../images/phase4-query-rewriter.png) | + small-LLM query rewriter, two LLM roles |
| [`final-architecture.puml`](final-architecture.puml) | [`final-architecture.png`](../images/final-architecture.png) | Everything, coloured by the phase that introduced it |

## Rendering

```bash
# one diagram
plantuml -tpng phase2-reranker.puml && mv phase2-reranker.png ../images/

# all of them
plantuml -tpng *.puml && mv *.png ../images/
```

`plantuml` needs Java and Graphviz (`apt install plantuml graphviz`). SVG also works
(`-tsvg`) if you'd rather have scalable output — the docs currently reference `.png`.

## Conventions these files share

Keeping these consistent is what makes the five diagrams read as **one system evolving** rather
than five unrelated pictures.

- **Component names are identical across all five files.** `Dense Retriever` is
  `Dense Retriever` everywhere — never "retriever" in one and "vector search" in another. The
  names also match the component catalogue in
  [ARCHITECTURE.md](../ARCHITECTURE.md#component-catalogue).
- **Colour carries one meaning per diagram.** In the phase diagrams: amber `#FFD98E` = NEW this
  phase, grey-blue `#EEF2F7` = carried over. In the final diagram, colour instead marks the phase
  that introduced each component. Both are spelled out in the diagram's own legend.
- **Fixed roles keep fixed colours** everywhere: red `#F5B7B1` = refusal, green `#A9DFBF` =
  rendered answer, purple `#D7BDE2` = eval harness.
- **`«seam»`** marks a pluggable interface from [SPEC.md](../SPEC.md#the-seams-pluggable-interfaces).
  `«gate»` marks a component that can refuse.
- **Solid arrow** = data flowing through the pipeline. **Dashed arrow** = a lookup into a seam or
  store, or eval/config instrumentation.
- **Arrows are labelled with what passes**, not with a verb — `top-20 candidates`, `reranked
  top-5`, `grounded prompt`.
- **Two packages, always**: `OFFLINE — ingestion` and `ONLINE — query`, plus `CROSS-CUTTING` for
  the eval harness and config. The offline/online split is the most important structural fact
  about the system, so it's visible before anything is read.
- Each file is **self-contained** (the style block is duplicated, not `!include`d) so any one can
  be pasted into an online PlantUML renderer or a blog post and still look right.

## When you change one

1. Edit the `.puml`, re-render, move the PNG into `../images/`.
2. **Apply the same change to every later phase's diagram** — Phase 3 contains Phase 2. A change
   that lands in only one file is how these drift.
3. Check the component catalogue in [ARCHITECTURE.md](../ARCHITECTURE.md#component-catalogue)
   still matches.
