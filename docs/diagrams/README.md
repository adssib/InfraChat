# Diagrams

Three diagrams, split by the question they answer. Sources here, rendered PNGs in
[`../images/`](../images/), committed alongside so the docs render on GitHub without a build step.

| Source | Renders to | Answers |
|---|---|---|
| [`ingest-sequence.puml`](ingest-sequence.puml) | [`ingest-sequence.png`](../images/ingest-sequence.png) | **In what order does ingestion happen** — and what makes a second ingest cheap (the manifest hash-compare, and delete-before-insert) |
| [`query-sequence.puml`](query-sequence.puml) | [`query-sequence.png`](../images/query-sequence.png) | **Where a query can stop** — the two refusal gates as `alt` branches, with later-phase components as optional groups |
| [`system.puml`](system.puml) | [`system.png`](../images/system.png) | **What exists and where it lives** — offline / store / online, coloured by the phase that introduced it |
| [`_style.inc`](_style.inc) | — | Shared palette and skinparams, `!include`d by all three |

## Why sequence diagrams carry most of the weight

This started as five component diagrams, one per phase. They were ~90% identical, so every change
had to be applied five times — a drift generator. Worse, a component diagram can only draw a
refusal as an arrow; it cannot show that a query **stops there**.

The two gates are the point of this project, and they are *branches*. Sequence diagrams draw
branches. So:

- **Order and control flow** → the two sequence diagrams. Later phases appear as grey `group`
  blocks, which shows in one picture what the five diagrams showed in five: everything Phases 2–4
  add sits *before* the gate, and the gate is untouched.
- **Structure** → `system.puml`, one component diagram, colour-coded by phase.

## Rendering

```bash
plantuml -tpng *.puml && mv *.png ../images/
```

Needs Java and Graphviz (`apt install plantuml graphviz`). `-tsvg` also works; the docs reference
`.png`.

## Conventions

- **Component names are identical across all three files** and match the component catalogue in
  [ARCHITECTURE.md](../ARCHITECTURE.md#component-catalogue). `Retriever` is `Retriever` everywhere.
- **Colour means phase** in `system.puml` (grey = Phase 1, amber = 2, green = 3, violet = 4).
  Fixed roles keep fixed colours everywhere: red = refusal, green = answer, purple = eval.
- **Solid arrow** = data through the pipeline. **Dashed** = a lookup, config, or instrumentation.
- **Arrows are labelled with what passes** — `top-20 chunk_ids + scores`, `grounded prompt` — not
  with a verb.
- **Grey `group` blocks** in the sequence diagrams mark components from a later phase.

## Layout notes (learned the hard way)

`system.puml` tangled badly on the first attempts. What fixed it:

- **Fewer cross-package edges.** Each package wires its own chain internally; only genuine
  hand-offs cross a boundary. Six near-parallel lines between `Retriever` and the store became one.
- **`Embedder` lives with the store**, not with ingestion — the query path calls `query_embed`
  too, so putting it in the offline package forced one long edge across the whole diagram.
- **`skinparam linetype ortho` hurt** — it routes long detours around packages. Plain `polyline`
  with the default top-down direction came out smallest and clearest. `left to right direction`
  made it *wider*, not narrower.
- **`config.yaml` / `sources.yaml` are a note, not nodes.** They feed every box, so drawing that
  honestly means edges to everything.

## When you change one

1. Edit the `.puml`, re-render, move the PNG into `../images/`.
2. Check the component catalogue in [ARCHITECTURE.md](../ARCHITECTURE.md#component-catalogue)
   still matches.
