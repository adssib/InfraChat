# InfraChat — Specification

> The **contract**: what the system must do, the shapes it must speak, and the bounds it
> must respect. *How* it's built lives in [ARCHITECTURE.md](ARCHITECTURE.md); *why* choices
> were made lives in [decisions/](decisions/); *in what order* lives in [ROADMAP.md](ROADMAP.md).
>
> **InfraChat** is a retrieval-augmented question-answering system over infrastructure
> documentation — the **Kubernetes** and **Docker** docs. Ask it "how does a multi-stage build
> work?" or "what is a Pod?" and it answers **from the docs, with citations**.
>
> Two convictions underpin the whole system:
> 1. **An answer without a citation is a bug, not a feature.** A RAG system that will happily
>    fabricate is a demo; one that *refuses when it cannot ground an answer* is a tool.
> 2. **Every retrieval component must earn its place with a measured delta.** InfraChat is built
>    as a baseline plus a series of additions (reranker, hybrid search, query rewriter), each
>    evaluated against the baseline so its value is a number, not a vibe.

## Corpus — what documents, from where

InfraChat's corpus is two open-source documentation trees, cloned locally:

| Source | Repository path | Content |
|---|---|---|
| **Kubernetes docs** | `github.com/kubernetes/website` → `/content/en/docs/concepts` | Kubernetes concepts: Pods, Services, Deployments, networking, storage, etc. |
| **Docker docs** | `github.com/docker/docs` → `/content` | Docker manuals: builds, Compose, networking, storage, engine, etc. |

- Both are large **markdown** trees — ideal RAG material (prose embeds and retrieves cleanly).
- v1 clones each repo and points InfraChat at the paths above. **Start with a subfolder** of each
  (e.g. Kubernetes `concepts/workloads`, Docker `content/manuals/build`) to keep first embedding
  runs cheap, then widen.
- **No live fetching/scraping in v1** — the docs are cloned to disk and ingested from there. A
  Git-URL clone step and live-fetch refresh is a noted [out-of-scope](#out-of-scope-deliberate-bounds)
  extension.

## Functional requirements

| ID | Requirement |
|---|---|
| **F1** | **Ingest** — walk the cloned Kubernetes + Docker doc trees, filter them, and produce chunks with source metadata. |
| **F2** | **Filter** — include only allowed doc types; hard-exclude secrets, binaries, and oversized files *before* embedding. |
| **F3** | **Chunk** — split docs into overlapping chunks, each carrying `source`, `source_doc`, and `source_location`; strip markdown frontmatter/template cruft. |
| **F4** | **Embed** — every chunk gets a vector embedding via a pluggable embedder (local model default, $0). |
| **F5** | **Store** — chunks + embeddings persist in a pluggable vector store; ingestion is repeatable and incremental per source. |
| **F6** | **Retrieve (dense)** — for a query, return the top-k chunks by vector similarity, each with score, source (k8s/docker), and location. |
| **F7** | **Grounded answer** — the LLM answers *using only retrieved chunks*; every answer carries the citations it used. |
| **F8** | **Refuse below floor** — if top-k similarity is below a configured confidence floor, return an explicit *"not in the docs"* refusal instead of answering. |
| **F9** | **Provenance required** — no answer renders without at least one citation. An uncited answer is rejected, never shown. |
| **F10** | **Source attribution** — every citation names which doc set it came from (Kubernetes or Docker) and the file/section. |
| **F11** | **Eval harness** — a fixed question set (answerable-from-k8s, answerable-from-docker, should-refuse) measures retrieval hit-rate and grounding/refusal correctness; runs are reproducible **and comparable across configurations** (baseline vs. +reranker vs. +hybrid vs. +rewriter). |
| **F12** | **Rerank (pluggable)** — an optional reranking stage reorders a larger candidate set by true relevance before grounding (retrieve top-N → rerank → keep top-k). Toggled by config. |
| **F13** | **Hybrid retrieval (pluggable)** — an optional keyword (BM25) index is fused with dense retrieval (rank fusion) before reranking. Toggled by config. |
| **F14** | **Query rewriting (pluggable)** — an optional small-LLM stage rewrites/expands the query before retrieval. Toggled by config. |
| **F15** | **Configurable** — corpus paths, chunk size, k, floor, embedder, store, reranker, hybrid, rewriter, and LLM are all driven by one YAML config. |
| **F16** | **Deployable demo** — the query UI runs locally and deploys to a free public host (Hugging Face Spaces) with a shareable URL. |

## Non-functional requirements

- **Broke-student stack** — local CPU embeddings, local vector store, cheap/free LLM API. Target cost: **~$0**.
- **Each phase is a working, demoable system** (see [ROADMAP.md](ROADMAP.md)) — never a big-bang integration at the end.
- **Pluggable seams** — embedder, vector store, retriever, reranker, query rewriter, and LLM client all sit behind interfaces so any one can be added or swapped **without touching the pipeline**. This is what makes the "add one component, measure the delta" plan possible.
- **Reproducible, comparable eval** — a fixed question set + a pinned corpus commit + a named config gives comparable numbers across every component addition.

## Contracts

These are the fixed interfaces between components. Bodies are the author's; the *shapes* are the spec.
The pipeline depends **only** on these interfaces — every optional component (reranker, hybrid,
rewriter) slots into an existing seam without rewiring the core.

### Core data shapes (define these FIRST)

```python
from dataclasses import dataclass
from enum import Enum

class Source(str, Enum):
    KUBERNETES = "kubernetes"
    DOCKER     = "docker"

@dataclass
class Chunk:
    id: str
    text: str
    source: Source             # which doc set (F10)
    source_doc: str            # e.g. "content/manuals/build/multi-stage.md"
    source_location: str       # e.g. "lines 40-58" — provenance, REQUIRED
    embedding: list[float] | None = None

@dataclass
class Retrieved:
    chunk: Chunk
    score: float               # relevance score in [0,1] (post-fusion/rerank if enabled)

@dataclass
class Citation:
    source: Source
    source_doc: str
    source_location: str

@dataclass
class Answer:
    text: str
    citations: list[Citation]  # REQUIRED, len >= 1 when grounded
    grounded: bool             # False => refused (below floor); citations empty only then
```

### Pipeline interfaces (the swap seams)

```python
from typing import Protocol

# --- Ingestion ---
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class VectorStore(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def search(self, query_vec: list[float], k: int) -> list[Retrieved]: ...

class KeywordIndex(Protocol):                      # Phase 3 (hybrid) — F13
    def add(self, chunks: list[Chunk]) -> None: ...
    def search(self, query: str, k: int) -> list[Retrieved]: ...

# --- Query path (each optional stage is a seam) ---
class QueryRewriter(Protocol):                     # Phase 4 — F14
    def rewrite(self, query: str) -> str: ...      # identity rewriter = no-op baseline

class Retriever(Protocol):
    # Dense in Phase 1; a hybrid implementation fuses dense + keyword in Phase 3.
    def retrieve(self, query: str, k: int) -> list[Retrieved]: ...

class Reranker(Protocol):                          # Phase 2 — F12
    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]: ...

class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...
```

**Every optional component is a null-object by default.** The baseline (Phase 1) uses an identity
`QueryRewriter` (returns the query unchanged), a dense-only `Retriever`, and a pass-through
`Reranker` (returns hits unchanged). Later phases swap in real implementations. This is why the
eval is a clean A/B: same pipeline, one seam changed.

### The query pipeline (how the seams compose)

```python
def answer_query(query: str, cfg, deps) -> Answer:
    q = deps.rewriter.rewrite(query)                           # Phase 4: real; baseline: identity
    candidates = deps.retriever.retrieve(q, k=cfg.retrieve_n)  # Phase 3: hybrid; baseline: dense
    hits = deps.reranker.rerank(q, candidates, top_k=cfg.k)    # Phase 2: real; baseline: pass-through

    # --- the grounding gate (the centerpiece) ---
    if not hits or hits[0].score < cfg.floor:
        return Answer("Not found in the Kubernetes or Docker docs.", [], grounded=False)

    prompt = build_grounded_prompt(q, hits)
    raw = deps.llm.complete(system=SYSTEM_PROMPT, user=prompt)
    ans = parse_answer(raw, hits)                              # maps cited chunks -> Citation[]

    if ans.grounded and not ans.citations:                    # uncited => contract violation
        return Answer("Insufficient grounding to answer.", [], grounded=False)
    return ans
```

**Refusing beats fabricating.** A confident wrong answer over infra docs destroys trust. The floor
(F8) and the citation requirement (F9) are the two gates that prevent it. Adding reranker/hybrid/
rewriter changes *what reaches the gate* — never the gate itself.

## LLM calling (the generation setup)

InfraChat calls an LLM through the `LLMClient` seam. Design goal: **provider-agnostic, cheap, swappable.**

### Client contract

```python
class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...

# Concrete adapters (config selects one):
#   OpenAICompatClient(base_url, model, api_key_env)   # OpenAI, Groq, Together, OpenRouter, local
#   LocalClient(model)                                 # llama.cpp / Ollama on the home-lab, $0
```

Most cheap/free providers expose an **OpenAI-compatible** endpoint, so one
`OpenAICompatClient(base_url=...)` covers OpenAI, Groq, Together, OpenRouter, and a local Ollama
server by changing `base_url` + `model`. The API key is read from an **environment variable** named
in config — **never** written in the YAML or committed.

> **Two LLM roles.** InfraChat uses an LLM in two places: the **generator** (answers from context,
> every phase) and the optional **query rewriter** (Phase 4, a *small/cheap* model). Both go through
> `LLMClient`; they are configured independently so the rewriter can use a cheaper model than the generator.

### The grounded prompt (how context is passed)

```python
SYSTEM_PROMPT = """You are InfraChat. Answer ONLY using the provided documentation excerpts.
Rules:
- Use only the excerpts. Do not use outside knowledge.
- If the excerpts do not contain the answer, reply exactly: NOT_IN_DOCS
- Cite the excerpt id(s) you used, in the form [source:location] after each claim.
- Be concise and technical."""

def build_grounded_prompt(query: str, hits: list[Retrieved]) -> str:
    blocks = []
    for h in hits:
        tag = f"{h.chunk.source.value}:{h.chunk.source_location}"
        blocks.append(f"[{tag}] ({h.chunk.source_doc})\n{h.chunk.text}")
    context = "\n\n---\n\n".join(blocks)
    return f"Documentation excerpts:\n\n{context}\n\nQuestion: {query}\n\nAnswer:"
```

- The model is **instructed to emit `NOT_IN_DOCS`** when context is insufficient — a second,
  model-level refusal path complementing the retrieval-floor refusal (F8). Either trip → refusal.
- Citations are parsed from the `[source:location]` tags the model echoes, then matched back to the
  retrieved chunks. A claim with no matchable tag does not count as grounded.

### Cost & safety controls

- **One generator call per query** — no agentic multi-hop in v1 (keeps cost and latency flat).
- **Context capped** at `max_context_chunks` so prompt size (and cost) is bounded.
- **API key via env var only** — read from `${INFRACHAT_LLM_API_KEY}`; never in config or git.
- **Local option** — `LocalClient` (Ollama/llama.cpp on the home-lab) makes the whole system $0.

## Configuration model (F15)

Components are toggled here — the config *is* the experiment. Each eval run pins one config.

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
    api_key_env: "INFRACHAT_LLM_API_KEY"   # env var name, NOT the key
    max_context_chunks: 5
  eval:
    question_set: "eval/questions.yaml"
    run_label: "baseline"              # names this config's results for comparison (F11)
```

## CLI / launch model

```
# clone the docs once (the v1 "source"):
git clone --depth 1 https://github.com/kubernetes/website corpus/kubernetes-website
git clone --depth 1 https://github.com/docker/docs        corpus/docker-docs

infrachat ingest -c config.yaml                 # walk, filter, chunk, embed, (optional) keyword-index
infrachat ask    -c config.yaml "how does a multi-stage build work?"
infrachat eval   -c config.yaml                 # run the fixed question set; print scores tagged run_label
infrachat serve  -c config.yaml                 # demo UI (also the HF Spaces entrypoint)
```

Subcommands (not flags) so `serve` maps cleanly onto a container / Spaces entrypoint.

## Out of scope (deliberate bounds)

- **Live fetching / scraping** of the docs (v1 clones them; a Git-URL clone-and-refresh step, then
  live web/API fetch, is a noted **later extension** — deferred so the RAG core reaches "done" first).
- **Doc sets beyond Kubernetes + Docker** — the two are fixed for v1; more sources is an extension.
- **Agentic multi-hop retrieval** — one retrieve (+optional rerank) + one generator call per query.
- **Fine-tuning / distillation** — this is *retrieval*, not training. Deliberately, and cheaply.
- **Multi-user / auth** — single-user local tool.

## Ethics & safety (non-negotiable)

- **Respect the source licenses.** The Kubernetes and Docker docs are openly licensed; honor their
  terms and attribute the source, especially before publishing a public demo.
- **API key hygiene is a hard rule.** The LLM key is read from an environment variable only — never
  in config, never committed. Secret files are excluded by pattern *before* embedding.
- **The refusal path (F8) is itself a safety feature.** InfraChat declines rather than fabricates:
  on infrastructure questions, a confident wrong answer is worse than an honest "not in the docs."
