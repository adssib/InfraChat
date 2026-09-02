# InfraChat

**Ask the Kubernetes and Docker docs a question — get an answer with citations, or an honest
"I don't know."**

A retrieval-augmented QA system over the [Kubernetes](https://github.com/kubernetes/website) and
[Docker](https://github.com/docker/docs) documentation, built as a **baseline plus one retrieval
component at a time** — reranker, hybrid search, query rewriter — with every addition measured
against the same eval set.

Two rules the whole system is built around: **an answer without a citation is a bug**, and
**every component must earn its place with a number.**

| | Doc |
|---|---|
| **What** must be true | [docs/SPEC.md](docs/SPEC.md) |
| **How** it's shaped | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **In what order** | [docs/ROADMAP.md](docs/ROADMAP.md) |
| **How it's measured** | [docs/EVAL.md](docs/EVAL.md) |
| **Why** (the ADR trail) | [docs/decisions/](docs/decisions/) |
| **Diagrams** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#how-the-system-grows) — baseline through final |

**Start here → [docs/README.md](docs/README.md)** · Status: **Phase 1 in progress** — ingestion path being built ([ROADMAP](docs/ROADMAP.md#current-status))
    