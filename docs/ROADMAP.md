# InfraChat — Roadmap

> The build order. **Each phase is an independently demoable, working system** — the project is
> always in a runnable state, never a big-bang integration at the end.
>
> The organizing idea: **build a baseline, then add one retrieval component at a time, and measure
> the delta against the baseline at every step.** Every phase (from Phase 2 on) is an experiment:
> *did this component earn its place?* The answers — with numbers — become the final write-up.

## Build order

| # | Phase | Delivers | Measure | Diagram |
|---|---|---|---|---|
| **1** | **Baseline RAG** — all systems wired | ingest → filter → chunk → embed → vector store; dense retrieve → grounding gate (floor → refuse) → LLM answer with citations; **eval harness** | **Eval run #1 → baseline numbers** | [P1](images/phase1-baseline.png) |
| **2** | **+ Reranker** | insert a cross-encoder reranker between retrieve and ground (retrieve top-20 → rerank → keep top-5) | Eval run #2 vs. baseline → *did reranking help?* | [P2](images/phase2-reranker.png) |
| **3** | **+ Hybrid search** | add a BM25 keyword index; fuse dense + keyword (reciprocal rank fusion) before reranking | Eval run #3 vs. Phase 2 → *did hybrid help, esp. on exact-term queries?* | [P3](images/phase3-hybrid.png) |
| **4** | **+ Query rewriter** | prepend a small/cheap LLM that rewrites/expands the query before retrieval | Eval run #4 vs. Phase 3 → *does rewriting earn its latency?* | [P4](images/phase4-query-rewriter.png) |
| **5** | **Deep-dive + deploy + write-up** | consolidate all runs into one comparison table; deploy to HF Spaces / home-lab; write the blog/report | The story: baseline → +reranker → +hybrid → +rewriter | [final](images/final-architecture.png) |

Each phase's diagram shows what it adds, in amber, on top of everything before it — the set reads
as one system growing. Sources: [diagrams/](diagrams/); walkthrough:
[ARCHITECTURE.md § How the system grows](ARCHITECTURE.md#how-the-system-grows).

Phase 1 is the whole pipeline at its simplest — everything after asks *"does adding X beat this
baseline?"* The eval harness (built in Phase 1) is the spine of the entire project.

## The measurement loop (why this project is worth talking about)

Each component phase follows the same loop:

1. **Baseline is fixed** (Phase 1's eval numbers on the fixed question set).
2. **Add exactly one component** via its seam (reranker / hybrid / rewriter), config-toggled.
3. **Re-run the same eval** → get the delta.
4. **Record it** — retrieval hit-rate, grounding correctness, refusal correctness, and (for
   rewriter) added latency/cost.
5. **Write a short section** on what that component bought — including honest negatives.

> This is what turns "I built a RAG system" into a real conversation: *"reranking gave me +X% on
> retrieval hit-rate, hybrid helped most on exact-term queries like flag names and error codes,
> and the query rewriter added latency for marginal gain — so I'd drop it in production."* A
> measured negative result (a component that didn't help) is a **strong** thing to report, not a failure.

## Definition of done (CV-worthy)

- [ ] **Baseline** works: ask "what is a Pod?" / "how does a multi-stage build work?"; get answers
      **with citations** naming the doc set + file/section.
- [ ] **Refusal** works: ask something in neither doc set (e.g. "how do I configure an AWS Lambda?");
      it refuses instead of hallucinating — demoable live, the most compelling moment.
- [ ] **Source attribution** works: a Kubernetes question cites Kubernetes docs, a Docker question
      cites Docker docs.
- [ ] **Eval harness** prints comparable scores per config (baseline, +reranker, +hybrid, +rewriter)
      over one fixed question set.
- [ ] **Each component measured**: a comparison table showing the delta each addition made.
- [ ] **LLM calling** works through the `LLMClient` seam with a cheap/free provider (or local model),
      key from an env var (never committed).
- [ ] **Deployed**: live on Hugging Face Spaces (public URL) or self-hosted on the home-lab.
- [ ] **Write-up**: a blog/report walking through the architecture and what each component bought,
      with numbers and honest conclusions.
- [x] Docs scaffolding: [SPEC.md](SPEC.md), [ARCHITECTURE.md](ARCHITECTURE.md), [EVAL.md](EVAL.md),
      the per-phase PlantUML diagrams, and the first ADRs (starting with
      [refuse over fabricate](decisions/0001-refuse-over-fabricate.md)).
- [ ] An ADR per phase decision that actually gets made, with the numbers that forced it.
- [ ] README leads with the refusal case and a cited answer — the project's POV.

## Notes on sequencing

- **Build the eval harness in Phase 1**, even minimally. Without it, "measure before and after" is
  just a vibe. The fixed question set (k8s-answerable + docker-answerable + should-refuse) makes
  every later delta real. **This is the single most important early decision.**
- **Phase 1 controls cost.** Local CPU embeddings + a **subfolder** of each doc set keep first runs
  free and fast. Do not embed both entire repos on day one — prove it on a subset, then widen.
- **Every component is config-toggled and defaults to off** (null-object). Turning one on is the
  experiment; the same code path runs baseline and enhanced, so comparisons are clean.
- **Phase 3 (hybrid) is where BM25 shines on exact-term queries** — flag names, error codes,
  API fields — the queries dense embeddings often miss. Design a few such questions into the eval set.
- **Fetching the docs live is a later extension**, outside this roadmap. It earns a phase only once
  Phases 1–5 hit "done."

## Current status

- **Phase 0 — docs and diagrams in place; no code yet.**
  - ✅ [SPEC](SPEC.md) (contracts + config), [ARCHITECTURE](ARCHITECTURE.md) (components + risks),
    [EVAL](EVAL.md) (question set + metrics).
  - ✅ Five [PlantUML diagrams](diagrams/) — baseline through final, rendered to [images/](images/).
  - ✅ ADRs [0001](decisions/0001-refuse-over-fabricate.md),
    [0002](decisions/0002-null-object-seams.md),
    [0003](decisions/0003-eval-harness-is-phase-1.md). Later decisions get an ADR when the phase
    lands, not before.
- **Phase 1 — not started.**
  - ⏳ Clone the two doc repos; confirm target subfolders + their markdown shape.
  - ⏳ Corpus filter (F2) — implement first; excluding secrets *before* embedding is the hard rule.
  - ⏳ Frontmatter-stripping chunker — the docs carry YAML frontmatter + template shortcodes.
  - ⏳ Local embedder + vector store behind the `Embedder` / `VectorStore` seams.
  - ⏳ Eval harness skeleton + first fixed question set (the spine).
