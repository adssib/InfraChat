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

The corpus is **declared in `sources.yaml`, not fixed in code** — adding a doc set is a YAML
entry ([ADR-0006](decisions/0006-pluggable-sources.md)). Two are configured today:

| Source | Repository → path | `clean` | Content |
|---|---|---|---|
| **Kubernetes** | `kubernetes/website` → `content/en/docs/concepts` | `hugo` | Pods, Services, Deployments, networking, storage |
| **Docker** | `docker/docs` → `content/manuals/build` | `hugo` | builds, Bake, multi-stage, caching, CI |

Each entry declares its root path, allowed extensions, and a **`clean` strategy** naming the
markup to strip (`plain` · `hugo` · `sphinx-rst`). That last field is what makes a differently
formatted doc set — Ansible's reStructuredText, say — a config change rather than a code change.

- Sources are cloned at a **pinned commit** and ingested from disk. **Sparse-clone the configured
  subfolder** rather than the whole repo: the two above are 13MB together, versus ~2GB full.
- **No live fetching in v1.** A clone-and-refresh step is a noted
  [out-of-scope](#out-of-scope-deliberate-bounds) extension.
- ⚠️ **Adding a source invalidates every prior eval run** — it changes the corpus and can flip a
  should-refuse question into an answerable one. Add one at a phase boundary, then re-baseline.

## Functional requirements

| ID | Requirement |
|---|---|
| **F1** | **Ingest** — walk the cloned Kubernetes + Docker doc trees, filter them, produce chunks with source metadata. |
| **F2** | **Filter** — include only allowed doc types; hard-exclude secrets, binaries, and oversized files *before* embedding. |
| **F3** | **Chunk** — split docs into overlapping chunks, each carrying source, doc path, and location; strip markdown frontmatter and template cruft. |
| **F4** | **Embed** — every chunk gets a vector embedding via a pluggable embedder (local model default, $0). |
| **F5** | **Store** — chunk text + provenance persist in the **chunk store** (the source of truth); embeddings in a pluggable vector store. Re-ingestion is **incremental**: a file whose content hash is unchanged is skipped; a changed file has its chunks deleted and rebuilt. |
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
| `source` | a configured source name, e.g. `kubernetes` | open string validated at config load against `sources.yaml` — **not a closed enum** (F10, [ADR-0006](decisions/0006-pluggable-sources.md)) |
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

## Storage

**One SQLite file, three roles.** None of them holds the documents: the markdown lives on disk in
the cloned repos at a pinned commit. What's stored is derived — chunks, vectors, postings — plus
the bookkeeping that makes re-ingestion incremental. See [ADR-0005](decisions/0005-one-sqlite-file.md).

| Role | Holds | Backed by | Why it exists |
|---|---|---|---|
| **Chunk Store** | chunk text + provenance, and the file manifest | `chunks` + `files` tables | the single source of truth every index is derived from |
| **Vector Store** | vectors keyed by `chunk_id` | `vec_chunks` — `sqlite-vec` `vec0` virtual table | nearest-neighbour search |
| **Keyword Index** (Phase 3) | the same chunks, tokenized | `fts_chunks` — FTS5 with `bm25()` | term search with real BM25 ranking |

All three live in **`data/infrachat.db`**. Because they share a connection, a vector search can
`JOIN` relational columns in one query rather than round-tripping through Python — which is what
makes per-source filtering and provenance hydration cheap.

### The two tables

| Table | One row per | Carries |
|---|---|---|
| `chunks` | chunk | `id` (TEXT, e.g. `kubernetes:architecture/cgroups.md#2`), `text`, `source`, `source_doc`, `source_location`, `file_id` |
| `files` | ingested file | `path`, `source`, `content_hash`, `ingested_at`, `chunk_count` |

### Why the manifest (F5)

`files` is what makes "incremental" implementable. On re-ingest, each file's content hash is
compared: **unchanged → skip**; **changed → delete its chunks by `file_id`, re-chunk, re-embed,
re-index**. Without it, a second ingest either duplicates every chunk or forces a full rebuild —
and there is no way to remove the chunks of a document that upstream deleted.

### Read path

Vector search returns **`chunk_id` + score**; text and provenance are hydrated from the chunk
store. **Chunk text is stored exactly once.** The cost is one extra local lookup per query; the
benefit is that the vector store and keyword index are both *derived artifacts* that can be
rebuilt from the chunk store without re-walking the corpus.

### Data directory & packaging

The data directory (`data_dir`, default `./data`) contains exactly one file, `infrachat.db`, and
is mounted as **a single Docker volume** — one mount, one thing to back up, one thing to delete
when starting clean.

⚠️ **The public demo does not mount a volume.** Free-tier hosted Spaces have an ephemeral
filesystem, so the deployed image ships a **pre-built, read-only index** and `infrachat ingest`
never runs inside it. Ingestion is a local/home-lab job whose output is an artifact.

### Eval results are not in the database

Per-question eval results are **flat JSONL** — `eval/runs/<run_label>.jsonl`, one row per
question, committed to the repo. Four runs of ~30 questions is not a database's problem, and a
committed results file is readable by anyone reviewing the repo. See [EVAL.md](EVAL.md).

## The seams (pluggable interfaces)

The pipeline depends **only** on these. Every optional component slots into an existing seam
without rewiring the core, and defaults to a **null object** so the baseline and the enhanced
system run the same code path.

| Seam | Responsibility | Real from | Baseline default |
|---|---|---|---|
| `ChunkStore` | persist chunks + the file manifest; hydrate chunks by id | Phase 1 | SQLite |
| `Cleaner` | strip a source's markup before chunking — the **per-source format seam** ([ADR-0006](decisions/0006-pluggable-sources.md)) | Phase 1 | `plain` (strip nothing) |
| `Embedder` | text → vectors, via **`passage_embed` and `query_embed`** — the default model is asymmetric, so a query is embedded differently from a passage | Phase 1 | `fastembed`, `bge-small-en-v1.5` |
| `VectorStore` | persist vectors keyed by `chunk_id`; similarity search for `k` | Phase 1 | `sqlite-vec`, same file |
| `Retriever` | question → ranked candidates | Phase 1 | dense-only |
| `Reranker` | reorder candidates by true relevance, keep top `k` | Phase 2 | **pass-through** |
| `KeywordIndex` | persist tokenized chunks; term search for `k` | Phase 3 | FTS5, same file |
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

**Two files.** The live copies are `sources.yaml` and `config.yaml` in the repo root; the shapes
below are the contract, and those files are the truth.

### `sources.yaml` — *what* gets ingested

Stable, and shared by every run. Separate from `config.yaml` because several experiment configs
use one corpus definition; duplicating it per config would silently break comparability.

```yaml
defaults:                          # merged under every source; a source may override any key
  exclude_globs: ["**/node_modules/**", "**/.git/**", "**/_print/**"]
  secret_patterns: [".env", "credentials*", "*.pem", "*.key", "id_rsa*"]
  max_file_bytes: 100000

sources:
  - name: kubernetes               # machine name — appears in chunk ids and citations
    label: "Kubernetes"            # human name — appears in the refusal message
    repo: "https://github.com/kubernetes/website"
    path: "corpus/kubernetes-website/content/en/docs/concepts"
    include_ext: [".md"]
    clean: hugo                    # plain | hugo | sphinx-rst
```

The **refusal message is generated from the `label` fields**, so a new source updates it for free.
`clean` selects the markup stripper — the per-source format seam.

### `config.yaml` — *how this run behaves*

One config = one eval run. Everything past Phase 1 is commented out; because every optional
component defaults to its null object, **a commented-out block and `enabled: false` mean exactly
the same thing.**

```yaml
infrachat:
  data_dir: "./data"                 # holds infrachat.db — one Docker volume
  corpus:
    sources_file: "sources.yaml"
  chunk:
    size: 800
    overlap: 100
  embedder:
    model: "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX via fastembed, no torch
  retrieval:
    retrieve_n: 20                   # candidates fetched (only matters once rerank is on)
    k: 5                             # final chunks sent to the LLM
    floor: 0.55                      # below this top-1 score => refuse (F8)
  eval:
    question_set: "eval/questions.yaml"
    results_dir: "eval/runs"
    run_label: "baseline"

  # llm:                             # needed from `ask` onward; `ingest` runs without it
  #   base_url: "https://api.groq.com/openai/v1"
  #   model: "llama-3.3-70b-versatile"
  #   api_key_env: "INFRACHAT_LLM_API_KEY"   # the env var NAME, never the key
  #   max_context_chunks: 5
  # rerank:   { enabled: true, model: "Xenova/ms-marco-MiniLM-L-6-v2" }   # Phase 2
  # retrieval: { hybrid: { enabled: true, fusion: rrf } }                 # Phase 3 — needs re-ingest
  # rewrite:  { enabled: true, model: "llama-3.1-8b-instant" }            # Phase 4
```

### Which keys have defaults

> **Anything that changes the numbers is required in YAML.
> Anything that turns a component off defaults to off.**

| Required — no default | Defaulted |
|---|---|
| `chunk.size`, `chunk.overlap` | `rerank`, `rewrite`, `hybrid` — the null objects |
| `embedder.model` | `llm` — absent means `ask` is unavailable, not an error |
| `retrieval.retrieve_n`, `k`, `floor` | `data_dir`, `sources_file`, `results_dir`, `question_set` |
| `eval.run_label` | |

A defaulted `chunk.size` or `floor` could differ from the value a recorded run actually used,
invalidating the comparison with no error. `eval.run_label` is required for a blunter reason: a
default would let a stray run overwrite the baseline results file.

**`floor` is embedder-specific.** 0.55 is a starting point measured against `bge-small-en-v1.5`,
where 0.35 refuses nothing — an unrelated question ("how do I bake sourdough bread?") scores 0.409
against these docs. Re-tune it on the real corpus, and again whenever the embedder changes.

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
- **Doc sets whose markup no `Cleaner` handles** — adding a source is a `sources.yaml` entry, but a
  new *format* needs a Cleaner implementation. Generated HTML and PDFs are out of scope.
- **Agentic multi-hop retrieval** — one retrieve (+optional rerank) and one generator call per query.
- **Fine-tuning / distillation** — this is *retrieval*, not training. Deliberately, and cheaply.
- **Multi-user / auth** — single-user local tool.
- **A hosted database during Phases 1–4** — the stores are local files behind a Docker volume, so
  latency measurements stay clean. Migrating to Postgres/pgvector is a **Phase 5 deployment**
  concern ([ADR-0004](decisions/0004-sqlite-chunk-store.md)).

## Ethics & safety (non-negotiable)

- **Respect the source licenses.** The Kubernetes and Docker docs are openly licensed; honor their
  terms and attribute the source, especially before publishing a public demo.
- **API key hygiene is a hard rule.** The LLM key is read from an environment variable only —
  never in config, never committed. Secret files are excluded by pattern *before* embedding: once
  text is in the index, it is retrievable.
- **The refusal path (F8/F9) is itself a safety feature.** InfraChat declines rather than
  fabricates: on infrastructure questions, a confident wrong answer is worse than an honest
  "not in the docs."
