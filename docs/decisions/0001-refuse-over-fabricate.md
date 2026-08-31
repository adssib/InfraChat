# ADR-0001: Refuse over fabricate — two independent gates

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 (the centerpiece)

## Context

A RAG system answers from retrieved text, but retrieval always returns *something* — vector
search has no concept of "nothing here." Ask about AWS Lambda over a corpus of Kubernetes and
Docker docs and you still get five chunks back, each with a similarity score. A naive pipeline
hands those to the LLM, and the LLM — instructed to be helpful — writes a fluent, confident,
wrong answer.

This is the default failure mode of every RAG demo, and it is worse than useless on
**infrastructure** questions specifically: a plausible wrong answer about `imagePullPolicy` or a
volume mount gets pasted into a real cluster. The cost of a confident error is asymmetric with
the cost of "I don't know."

Two things can go wrong, and they're independent:
1. Retrieval brings back nothing relevant.
2. Retrieval brings back something *plausible but insufficient*, and the model answers anyway.

## Decision

**No answer renders without grounding, and grounding is checked twice** — at two gates that trip
at different stages, either of which is enough to withhold an answer:

- **Gate 1 — retrieval floor (F8).** If the top-1 similarity score is below `retrieval.floor`,
  refuse before calling the LLM at all: *"Not found in the Kubernetes or Docker docs."*
- **Gate 2 — citation check (F9).** The system prompt instructs the model to emit exactly
  `NOT_IN_DOCS` when the excerpts don't answer the question, and every claim must carry a
  `[source:location]` tag that matches back to a retrieved chunk. `NOT_IN_DOCS`, or an answer with
  no matchable tag, refuses: *"Insufficient grounding to answer."*

**An answer without a citation is a bug, not a feature.**

## Alternatives considered

- **Answer with a confidence caveat** ("I'm not certain, but...") — softens the wrong answer
  without removing it. Readers skim caveats; the wrong `kubectl` command still gets run.
- **Floor only, no citation check** — cheap, but the failure it misses is the important one:
  retrieval returning topically-similar-but-insufficient chunks that clear the floor. Similarity
  is not sufficiency.
- **Citation check only, no floor** — catches more, but pays for an LLM call on every
  hopeless query, and leans entirely on the model obeying an instruction.
- **Let the LLM use outside knowledge when retrieval is thin** — this is exactly the "helpful"
  behaviour being engineered *out*. The value proposition is that a cited answer came from the
  docs; the moment outside knowledge leaks in, no answer can be trusted.

## Consequences

- ✅ **A refusal is a correct answer**, not an error path — and it's the most compelling thing to
  demo, because it's the part nobody else shows.
- ✅ **Two gates fail independently** — one is model-free and cheap, the other catches what
  similarity scores can't see.
- ✅ Gate 1 also **saves money**: hopeless queries never reach the LLM.
- ⚠️ **False refusals become a real failure mode.** Set the floor too high and the system refuses
  questions the docs *do* answer. This is why `false-refusal rate` is a first-class metric in
  [EVAL.md](../EVAL.md) — a system that refuses everything scores perfectly on refusal recall.
- ⚠️ **The floor is a tuned constant, not a probability.** It's calibrated against one embedder's
  score distribution and **must be re-tuned whenever the embedder changes**.
- ⚠️ Gate 2 depends on the model **following an instruction**. A weak model may ignore
  `NOT_IN_DOCS`; the citation-matching check is the backstop that doesn't depend on obedience.
- 🔭 Revisit if false refusals dominate the eval — the fix would be a calibrated, per-query
  threshold rather than a global constant, not removing the gate.
