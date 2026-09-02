# InfraChat — Documentation

Start here. The docs are split by **purpose**, so a reviewer can find what they need fast.

| Doc | Answers |
|---|---|
| [SPEC.md](SPEC.md) | **What** must be true — requirements, data shapes, the pluggable seams, the grounding gate, corpus, config, scope, ethics. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **How** it's shaped — components, the offline/online split, the phase-by-phase diagrams, assumptions and risks. |
| [ROADMAP.md](ROADMAP.md) | **In what order** — the 5-phase build plan and the definition of done. |
| [EVAL.md](EVAL.md) | **How it's measured** — the question set, the metric definitions, and the comparison table every phase fills in. |
| [decisions/](decisions/) | **Why** — Architecture Decision Records: every tradeoff, on the record. |
| [diagrams/](diagrams/) | The PlantUML sources for every diagram (rendered into [images/](images/)). |

## Reading path

**SPEC → ARCHITECTURE → skim the ADRs.** If you only read one thing, read
[ADR-0001: refuse over fabricate](decisions/0001-refuse-over-fabricate.md) — it is the decision
the rest of the system is arranged around. If you only look at one picture, look at
[the final architecture](images/final-architecture.png).

## The one-paragraph version

InfraChat ingests two markdown documentation trees **offline** (load → filter → chunk → store →
embed → index), and answers questions **online** (rewrite → retrieve → fuse → rerank → **grounding gate**
→ generate → citation check). The gate is the point of the project: if retrieval confidence is
below a floor, or the model cannot ground an answer in the retrieved excerpts, InfraChat
**refuses** instead of guessing. Every optional component sits behind an interface and defaults
to a **null object**, so turning one on is a controlled experiment against a fixed eval set.

> **Not here yet:** there is no usage guide, because there is nothing to run — the CLI shape is a
> contract in [SPEC.md](SPEC.md#cli--launch-model) until Phase 1 makes it real.

## Doc conventions

- **SPEC is the contract.** If the code and the SPEC disagree, one of them is a bug — say which.
- **ARCHITECTURE holds the diagrams.** Diagram sources live in [diagrams/](diagrams/); rendered
  PNGs live in [images/](images/). Change the `.puml`, re-render, commit both.
- **Every non-trivial decision gets an ADR** — context → options → tradeoff → consequences.
  When a decision changes, write a *new* ADR and mark the old one **Superseded**; never rewrite it.
- **Present tense means it exists.** Anything not built yet is marked with its phase.
