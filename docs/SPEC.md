# InfraChat — Specification

> The **contract**: what the system must do, the shapes it must speak, and the bounds it must
> respect. *How* it's built lives in [ARCHITECTURE.md](ARCHITECTURE.md); *why* choices were made
> lives in [decisions/](decisions/); *in what order* lives in [ROADMAP.md](ROADMAP.md); how it's
> scored lives in [EVAL.md](EVAL.md).
>
> This document says **what must be true**, not how to write it. Field lists and interfaces here
> fix the *shape* of the contract — the implementation is the author's.

InfraChat answers questions over the **Kubernetes** and **Docker** docs, **from the docs, with
citations** — or it refuses. It is built as a baseline plus one retrieval component at a time,
each measured against that baseline.

## Corpus — what documents, from where

| Source | Repository path | Content |
|---|---|---|
| **Kubernetes docs** | `github.com/kubernetes/website` → `/content/en/docs/concepts` | Pods, Services, Deployments, networking, storage |
| **Docker docs** | `github.com/docker/docs` → `/content` | builds, Compose, networking, storage, engine |

- Both are large **markdown** trees — prose that embeds and retrieves cleanly.
- v1 clones each repo at a **pinned commit** and ingests from disk. **Start with a subfolder** of
  each (Kubernetes `concepts/workloads`, Docker `content/manuals/build`) to keep first runs cheap,
  then widen.
- **No live fetching in v1.** A clone-and-refresh step is a noted
  [out-of-scope](#out-of-scope-deliberate-bounds) extension.

## Functional requirements

| ID | Requirement |
|---|---|
| **F1** | **Ingest** — walk the cloned Kubernetes + Docker doc trees, filter them, produce chunks with source metadata. |
| **F2** | **Filter** — include only allowed doc types; hard-exclude secrets, binaries, and oversized files *before* embedding. |
| **F3** | **Chunk** — split docs into overlapping chunks, each carrying source, doc path, and location; strip markdown frontmatter and template cruft. |
| **F4** | **Embed** — every chunk gets a vector embedding via a pluggable embedder (local model default, $0). |
| **F5** | **Store** — chunks + embeddings persist in a pluggable vector store; ingestion is repeatable and incremental per source. |
| **F6** | **Retrieve (dense)** — for a query, return the top-k chunks by vector similarity, each with score, source, and location. |
| **F7** | **Grounded answer** — the LLM answers *using only retrieved chunks*; every answer carries the citations it used. |
| **F8** | **Refuse below floor** — if top-1 similarity is below a configured floor, return an explicit *"not in the docs"* refusal instead of answering. |
| **F9** | **Provenance required** — no answer renders without at least one citation. An uncited answer is rejected, never shown. |
| **F10** | **Source attribution** — every citation names which doc set it came from (Kubernetes or Docker) and the file/section. |
| **F11** | **Eval harness** — a fixed question set (k8s-answerable, docker-answerable, should-refuse) measures retrieval and grounding/refusal correctness; runs are reproducible **and comparable across configurations**. See [EVAL.md](EVAL.md). |
| **F12** | **Rerank (pluggable)** — an optional stage reorders a larger candidate set by true relevance before grounding. Toggled by config. |
| **F13** | **Hybrid retrieval (pluggable)** — an optional keyword (BM25) index is fused with dense retrieval before reranking. Toggled by config. |
| **F14** | **Query rewriting (pluggable)** — an optional small-LLM stage rewrites/expands the query before retrieval. Toggled by config. |
| **F15** | **Configurable** — corpus paths, chunking, k, floor, embedder, store, reranker, hybrid, rewriter, and LLM are all driven by one YAML config. |
| **F16** | **Deployable demo** — the query UI runs locally and deploys to a free public host with a shareable URL. |

## Non-functional requirements

- **Broke-student stack** — local CPU embeddings, local vector store, cheap/free LLM API. Target: **~$0**.
- **Each phase is a working, demoable system** ([ROADMAP.md](ROADMAP.md)) — never a big-bang integration.
- **Pluggable seams** — every component sits behind an interface, so any one can be swapped
  **without touching the pipeline** ([ADR-0002](decisions/0002-null-object-seams.md)).
- **Reproducible, comparable eval** — fixed question set + pinned corpus commit + named config.

## Data shapes

What the system passes between components. Field lists are the contract; representation is the
author's.

### `Chunk` — the unit of retrieval

| Field | Carries | Why it's in the contract |
|---|---|---|
| `id` | stable chunk identifier | a citation must map back to one specific chunk |
| `text` | the excerpt | this is what the LLM is allowed to use |
| `source` | `kubernetes` \| `docker` | F10 — every citation names its doc set |
| `source_doc` | path within the doc set | the "which file" half of provenance |
| `source_location` | line range or section | **required, never optional** — a citation without it isn't checkable |
| `embedding` | the vector | absent until the embedder runs |

### The rest

| Type | Contract |
|---|---|
| `Retrieved` | a `Chunk` plus a `score` in `[0,1]` — **post-fusion / post-rerank when those are enabled** |
| `Citation` | `source` + `source_doc` + `source_location` — the three things a reader needs to verify a claim |
| `Answer` | `text`, `citations` (**≥1 when grounded**, empty *only* on a refusal), and `grounded` (`false` ⇒ refused) |

⚠️ `score` is the field the grounding gate reads. Whatever stage last wrote it defines what
`floor` means — see [ARCHITECTURE.md § Assumptions](ARCHITECTURE.md#assumptions--risks-on-the-record).

## The seams (pluggable interfaces)

The pipeline depends **only** on these. Every optional component slots into an existing seam
without rewiring the core, and defaults to a **null object** so the baseline and the enhanced
system run the same code path.

| Seam | Responsibility | Real from | Baseline default |
|---|---|---|---|
| `Embedder` | text → vectors. **The same instance embeds chunks and queries** | Phase 1 | local CPU model |
| `VectorStore` | persist chunks + vectors; similarity search for `k` | Phase 1 | Chroma |
| `Retriever` | question → ranked candidates | Phase 1 | dense-only |
| `Reranker` | reorder candidates by true relevance, keep top `k` | Phase 2 | **pass-through** |
| `KeywordIndex` | persist tokenized chunks; term search for `k` | Phase 3 | absent |
| `Fusion` | merge two ranked lists into one ranking | Phase 3 | absent |
| `QueryRewriter` | question → rewritten question | Phase 4 | **identity** |
| `LLMClient` | (system prompt, user prompt) → completion | Phase 1 | OpenAI-compatible |

## The query pipeline

```
query ─▶ rewrite ─▶ retrieve ─▶ [fuse] ─▶ rerank ─▶ GROUNDING GATE ─▶ prompt ─▶ generate ─▶ CITATION CHECK ─▶ answer
                                                          │                                        │
                                                    below floor                            NOT_IN_DOCS / uncited
                                                          ▼                                        ▼
                                                       REFUSE                                   REFUSE
```

Stages run in that order, always. Enabling a component changes **what reaches the gate** — never
the order, and never the gate.

### The two gates (the centrepiece)

Both must pass before an answer renders. They are independent; either one alone is enough to
refuse.

| | **Gate 1 — retrieval floor (F8)** | **Gate 2 — citation check (F9)** |
|---|---|---|
| Trips when | no hits, or top-1 `score` < `retrieval.floor` | completion is exactly `NOT_IN_DOCS`, **or** no claim carries a tag matching a retrieved chunk |
| Runs | before the LLM is called | after the LLM returns |
| Message | *"Not found in the Kubernetes or Docker docs."* | *"Insufficient grounding to answer."* |
| Costs | nothing — the LLM is never called | one LLM call |

**No answer renders with zero citations.** See [ADR-0001](decisions/0001-refuse-over-fabricate.md).

### Format contracts

Two literal strings the system depends on. Changing either is a breaking change:

- **`NOT_IN_DOCS`** — the exact sentinel the generator emits when the excerpts don't answer the
  question. Matched literally.
- **`[source:location]`** — the citation tag the generator appends to each claim, e.g.
  `[kubernetes:concepts/workloads/pods]`. Tags are parsed out and matched back to retrieved
  chunks; **a tag that matches nothing does not count as grounding**.

## LLM calling

InfraChat calls an LLM through the `LLMClient` seam. Design goal: **provider-agnostic, cheap,
swappable.**

| Requirement | Contract |
|---|---|
| Provider | any **OpenAI-compatible** endpoint — OpenAI, Groq, Together, OpenRouter, or a local Ollama / llama.cpp server. Switching is `base_url` + `model`. |
| Credentials | the API key is read from an **environment variable named in config** — never written in YAML, never committed. |
| Calls per query | **one generator call.** No agentic multi-hop in v1, so cost and latency stay flat. |
| Context bound | capped at `max_context_chunks` so prompt size is bounded. |
| Local option | a local model makes the whole system **$0**. |

**Two LLM roles.** The **generator** answers from context (every phase); the optional **query
rewriter** (Phase 4) is a *small, cheap* model. Both go through `LLMClient`, **configured
independently**, so the rewriter can run a much cheaper model than the generator.

The prompt wording is the author's; these four rules are the contract: **answer only from the
excerpts, no outside knowledge**; **reply exactly `NOT_IN_DOCS`** when they don't contain the
answer; **cite `[source:location]` after each claim**; be concise and technical. Each excerpt is
passed in tagged with its `[source:location]`, so the tags the model echoes are matchable.

## Configuration model (F15)

Components are toggled here — **the config is the experiment.** Each eval run pins one config.

```yaml
infrachat:
  corpus:
    sources:
      - name: kubernetes
        path: "./corpus/kubernetes-website/content/en/docs/concepts"
      - name: docker
        path: "./corpus/docker-docs/content"
    include_ext: [".md", ".mdx"]
    exclude_globs: ["**/node_modules/**", "**/.git/**", "**/*.png", "**/*.svg", "**/_*"]
    secret_patterns: [".env", "*secret*", "*_key*", "credentials*"]   # never embed
    max_file_bytes: 100000
    strip_frontmatter: true
  chunk:
    size: 800
    overlap: 100
  embedder: local                      # local | api
  store: chroma                        # chroma | pgvector
  retrieval:
    retrieve_n: 20                     # candidates fetched before rerank
    k: 5                               # final chunks sent to the LLM
    floor: 0.35                        # below this top-1 score => refuse (F8)
    hybrid:                            # F13 — Phase 3
      enabled: false                   # false = dense-only baseline
      keyword_index: bm25
      fusion: rrf                      # reciprocal rank fusion
  rerank:                              # F12 — Phase 2
    enabled: false                     # false = pass-through baseline
    model: "<cross-encoder-model>"
  rewrite:                             # F14 — Phase 4
    enabled: false                     # false = identity baseline
    model: "<small-cheap-model>"
  llm:                                 # the generator
    client: openai_compat              # openai_compat | local
    base_url: "https://api.<provider>.com/v1"
    model: "<cheap-or-free-model>"
    api_key_env: "INFRACHAT_LLM_API_KEY"   # env var NAME, not the key
    max_context_chunks: 5
  eval:
    question_set: "eval/questions.yaml"
    run_label: "baseline"              # names this config's results for comparison (F11)
```

**Held fixed across all phases** so eval runs stay comparable: `chunk.*`, `embedder`, and the
corpus commit. Changing any of them invalidates comparison with earlier runs — see
[EVAL.md](EVAL.md).

## CLI / launch model

```
# clone the docs once (the v1 "source"):
git clone --depth 1 https://github.com/kubernetes/website corpus/kubernetes-website
git clone --depth 1 https://github.com/docker/docs        corpus/docker-docs
```

| Command | Does | Path |
|---|---|---|
| `infrachat ingest -c config.yaml` | walk, filter, chunk, embed, (optional) keyword-index | offline |
| `infrachat ask -c config.yaml "<question>"` | one question → cited answer or refusal | online |
| `infrachat eval -c config.yaml` | run the fixed question set, print scores tagged `run_label` | both |
| `infrachat serve -c config.yaml` | demo UI; also the public-host entrypoint | online |

Subcommands (not flags) so `serve` maps cleanly onto a container entrypoint. Re-ingest is needed
only when the **offline** path changes — enabling hybrid adds an index, so Phase 3 needs one;
enabling the reranker or rewriter does not.

## Out of scope (deliberate bounds)

- **Live fetching / scraping** of the docs — v1 clones them; clone-and-refresh, then live fetch,
  is a noted later extension, deferred so the RAG core reaches "done" first.
- **Doc sets beyond Kubernetes + Docker** — fixed for v1.
- **Agentic multi-hop retrieval** — one retrieve (+optional rerank) and one generator call per query.
- **Fine-tuning / distillation** — this is *retrieval*, not training. Deliberately, and cheaply.
- **Multi-user / auth** — single-user local tool.

## Ethics & safety (non-negotiable)

- **Respect the source licenses.** The Kubernetes and Docker docs are openly licensed; honor their
  terms and attribute the source, especially before publishing a public demo.
- **API key hygiene is a hard rule.** The LLM key is read from an environment variable only —
  never in config, never committed. Secret files are excluded by pattern *before* embedding: once
  text is in the index, it is retrievable.
- **The refusal path (F8/F9) is itself a safety feature.** InfraChat declines rather than
  fabricates: on infrastructure questions, a confident wrong answer is worse than an honest
  "not in the docs."
