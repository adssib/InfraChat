# InfraChat — Roadmap

> The build order. **Each phase is an independently demoable, working system** — the project is
> always in a runnable state, never a big-bang integration at the end.
>
> The organizing idea: **build a baseline, then add one retrieval component at a time, and measure
> the delta against the baseline at every step.** Every phase (from Phase 2 on) is an experiment:
> *did this component earn its place?* The answers — with numbers — become the final write-up.

## Build order

| # | Phase | Delivers | Measure |
|---|---|---|---|
| **1** | **Baseline RAG** — all systems wired | ingest → filter → chunk → **chunk store** → embed → vector store; dense retrieve → grounding gate (floor → refuse) → LLM answer with citations; **eval harness** | **Eval run #1 → baseline numbers** |
| **2** | **+ Reranker** | insert a cross-encoder reranker between retrieve and ground (retrieve top-20 → rerank → keep top-5) | Eval run #2 vs. baseline → *did reranking help?* |
| **3** | **+ Hybrid search** | add a BM25 keyword index; fuse dense + keyword (reciprocal rank fusion) before reranking | Eval run #3 vs. Phase 2 → *did hybrid help, esp. on exact-term queries?* |
| **4** | **+ Query rewriter** | prepend a small/cheap LLM that rewrites/expands the query before retrieval | Eval run #4 vs. Phase 3 → *does rewriting earn its latency?* |
| **5** | **Deep-dive + deploy + write-up** | consolidate all runs into one comparison table; deploy to HF Spaces / home-lab; **optional Postgres + pgvector migration** ([ADR-0004](decisions/0004-sqlite-chunk-store.md)); write the blog/report | The story: baseline → +reranker → +hybrid → +rewriter |

Every phase appears in the same two [sequence diagrams](diagrams/) — later-phase components are
drawn as optional groups, so one picture shows the whole progression. Walkthrough:
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
- **Storage stays local through Phase 4.** The stores are files behind one Docker volume so no
  network hop lands inside the p95 numbers Phase 4 is judged on. Postgres/pgvector is a Phase 5
  deployment variant, taken after the measurements are locked.

## Current status

**Phase 1 — in progress.** The offline path is being built module by module; nothing is wired
into a CLI yet.

Done:

- ✅ Docs: [SPEC](SPEC.md), [ARCHITECTURE](ARCHITECTURE.md), [EVAL](EVAL.md), five
  [diagrams](diagrams/), ADRs [0001](decisions/0001-refuse-over-fabricate.md)–[0006](decisions/0006-pluggable-sources.md).
- ✅ **Corpus cloned** — sparse checkout of the two configured subfolders, 13MB, 307 files.
- ✅ `models.py` — Chunk / Retrieved / Citation / Answer. F9 is enforced in the type: an uncited
  grounded answer cannot be constructed.
- ✅ `config.py` + `config.yaml` + `sources.yaml` — two-file config, per-source `clean` seam,
  generated refusal message, later phases commented out.
- ✅ `ingest/loader.py` — deterministic walk, source-relative paths.
- ✅ `ingest/filter.py` — F2, every drop carries the rule that caused it.

Next, in order:

- ⏳ `ingest/chunker.py` — frontmatter + Hugo shortcode stripping, overlapping windows.
- ⏳ `store/chunks.py` — the one SQLite file: `chunks`, `files`, `vec_chunks`.
- ⏳ `embed.py` — the `Embedder` seam (fastembed, asymmetric query/passage).
- ⏳ `cli.py` — `ingest` and `ingest --dry-run`, the first runnable command.
- ⏳ Then the online path: retriever → gate → prompt → LLM → citation check → `ask`.
- ⏳ Then `serve` (Gradio), the eval harness + question set, Docker, and the Spaces deploy.

Open decisions blocking nothing but worth settling: narrowing `secret_patterns` (today `*secret*`
excludes the Kubernetes Secrets docs), and whether `_index.md` should be stripped from citation tags.
