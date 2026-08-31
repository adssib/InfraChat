# InfraChat

**Ask the Kubernetes and Docker docs a question — get an answer with citations, or an honest
"I don't know."**

InfraChat is a retrieval-augmented question-answering system over two infrastructure
documentation sets:

- **Kubernetes docs** — [`kubernetes/website`](https://github.com/kubernetes/website) →
  `/content/en/docs/concepts`
- **Docker docs** — [`docker/docs`](https://github.com/docker/docs) → `/content`

Ask *"what is a Pod?"* or *"how does a multi-stage build work?"* and InfraChat retrieves the
relevant documentation, answers **strictly from it**, and **cites the exact file and section**
it used. Ask something the docs don't cover and it **refuses** rather than making something up.

## Two convictions

**1. An answer without a citation is a bug, not a feature.**
Most RAG demos will happily hallucinate a confident, wrong answer. InfraChat won't:
- If retrieval confidence is below a floor → *"not in the docs."*
- If the model can't answer from the retrieved excerpts → it emits `NOT_IN_DOCS` → refusal.
- Every answer that renders carries citations naming the doc set (Kubernetes or Docker) + section.

**Refusing beats fabricating.** On infrastructure questions, a confident wrong answer is worse
than an honest "I don't know."

**2. Every retrieval component must earn its place with a measured delta.**
InfraChat is built as a **baseline plus a series of additions** — a reranker, hybrid search, a
query rewriter — and each one is **evaluated against the baseline** so its value is a number, not
a vibe. The result is a project you can actually reason about: *what did each component buy?*

## How it grows (the component story)

The system is built in phases, adding one retrieval component at a time and re-running the same
evaluation at each step:

| Phase | System | Question it answers |
|---|---|---|
| 1 | **Baseline RAG** (dense retrieval → ground → answer) | What's the starting point? |
| 2 | **+ Reranker** (cross-encoder reorders candidates) | Does reranking improve retrieval? |
| 3 | **+ Hybrid search** (BM25 fused with dense) | Does keyword+dense beat dense alone? |
| 4 | **+ Query rewriter** (small LLM expands the query) | Does rewriting earn its latency? |
| 5 | **Deep-dive + deploy + write-up** | What did each component *actually* buy? |

Every phase is independently runnable. The eval harness (built in Phase 1) is the spine — it makes
every "before vs. after" a real measurement. See [ROADMAP.md](ROADMAP.md) for the full plan.

## How it works

```## This needs to be Memrmaid Doc not this loool 
                          OFFLINE (ingest)
cloned docs ─▶ filter ─▶ chunk ─▶ embed ─▶ vector store
                                    └─────▶ keyword index (BM25, hybrid phase)

                          ONLINE (query)
query ─▶ [rewrite] ─▶ retrieve (dense │ hybrid) ─▶ [rerank] ─▶ grounding gate
                                                                     │
                                              below floor? ─▶ REFUSE
                                                                     │
                                       LLM (context only) ─▶ answer + citations
                                                                     │
                                              no citation? ─▶ REFUSE
```

`[rewrite]` and `[rerank]` are optional stages added in later phases. Every stage — embedder,
vector store, retriever, reranker, query rewriter, LLM client — sits behind an interface, so any
one can be added or swapped **without touching the pipeline**. That's what makes the
"add one component, measure the delta" plan work.

The LLM seam is **OpenAI-compatible**, so it runs against a cheap hosted provider *or* a local
model (Ollama / llama.cpp) for a fully **$0** setup.

Full details:
- **[SPEC.md](SPEC.md)** — *what* must be true: requirements, data shapes, the pluggable component
  seams, the grounding gate, the LLM-calling setup, corpus definition, config, scope, ethics.
- **[ROADMAP.md](ROADMAP.md)** — *in what order*: the phased build + the measurement loop.
- **[decisions/](decisions/)** — *why*: the ADR trail (start with "refuse over fabricate").

## Quick start

```bash
# 1. Clone the two doc sets (the corpus source)
git clone --depth 1 https://github.com/kubernetes/website corpus/kubernetes-website
git clone --depth 1 https://github.com/docker/docs        corpus/docker-docs

# 2. Set your LLM API key (env var only — never commit it)
export INFRACHAT_LLM_API_KEY="sk-..."      # or run a local model and skip this

# 3. Ingest the docs into the vector store
infrachat ingest -c config.yaml

# 4. Ask
infrachat ask -c config.yaml "how does a multi-stage build work?"

# 5. Or serve the demo UI
infrachat serve -c config.yaml
```

> **Tip:** for a fast, cheap first run, point the corpus at a *subfolder* of each doc set
> (e.g. Kubernetes `concepts/workloads`, Docker `manuals/build`) before ingesting everything.

## Example

**Answerable (Kubernetes):**
```
Q: What is a Pod?
A: A Pod is the smallest deployable unit in Kubernetes, a group of one or more
   containers with shared storage and network. [kubernetes:concepts/workloads/pods]
```

**Answerable (Docker):**
```
Q: How does a multi-stage build work?
A: A multi-stage build uses multiple FROM statements so build artifacts can be
   copied into a smaller final image, keeping it lean. [docker:manuals/build/multi-stage]
```

**Refusal (in neither doc set):**
```
Q: How do I configure an AWS Lambda function?
A: Not found in the Kubernetes or Docker docs.
```

## Cost

Designed to run for **~$0**: local CPU embeddings, a local vector store, and either a free-tier
LLM API or a local model on your own hardware.

## Ethics & safety

- Respects the source licenses (Kubernetes and Docker docs are openly licensed) — attribute the
  source, especially in a public demo.
- The LLM API key is read from an environment variable only — never in config, never committed.
  Secret files are excluded before embedding.
- The refusal path is a safety feature, not a limitation: InfraChat declines rather than fabricates.

## Status

Early — see [ROADMAP.md](ROADMAP.md) for the current phase. Built spec-first: the contract is
defined before the code, every phase is independently runnable, and every component is measured.
