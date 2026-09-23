# ADR-0010: The query rewriter steers retrieval only — and does not ship

- **Status:** Accepted
- **Date:** 2026-09-23
- **Phase:** 4

## Context

Phase 4 adds a small-LLM query rewriter ahead of retrieval. Users describe symptoms ("my
image is too big"); the documentation names mechanisms ("multi-stage build"). The
rewriter was meant to bridge that, and the `paraphrase` slice — the lowest-scoring slice
after Phase 2, at 0.727 MRR — was its target.

Three things turned out to depend on *which string* each stage sees, and the pipeline
had never had to decide, because the identity rewriter made the question and the query
the same string:

1. **The generator.** The grounded prompt was built from the rewritten query, so a real
   rewriter would have had the model answer its own keyword expansion. Fixed first.
2. **The reranker.** It was scoring (expanded query, chunk) pairs.
3. **The gate.** It reads cosine similarity to whatever query the retriever embedded.

The rewriter itself runs on `gpt-oss-20b` at `reasoning_effort: low` (~0.3–0.5s,
~140 tokens) — `llama-3.1-8b-instant` is gated on Groq. It **appends** terms to the
question rather than replacing it; a replacement measured as drifting from what the user
asked. Every arm below read the same cached rewrite (`eval/runs/+rewriter-queries.json`),
so rewriter nondeterminism cannot show up as an arm difference.

## Decision

**The rewrite steers retrieval, and only retrieval. Everything that judges — the
generator's prompt and the reranker — uses the user's original question.**

**And the rewriter does not ship.** `rewrite.enabled` stays `false`. It is recorded here
as a measured negative, with the best variant measured so it does not have to be
re-litigated.

## Measurements (all 87 questions, retrieval only)

| arm | MRR | paraphrase | exact-term |
|---|---|---|---|
| dense | 0.788 | 0.667 | 0.833 |
| dense + rewrite | 0.834 | 0.659 | 0.896 |
| hybrid | 0.845 | 0.699 | 0.914 |
| hybrid + rewrite | 0.814 | 0.764 | 0.865 |
| reranker | 0.867 | 0.727 | 0.919 |
| reranker + rewrite, reranking the **expansion** | 0.820 | 0.713 | 0.891 |
| **dense + rewrite, reranking the original question** | **0.875** | **0.782** | — |

## Alternatives considered

- **Ship the rewriter as specified** (rewrite feeds everything). It helps only the weakest
  configuration and hurts both better ones: hybrid −0.031, reranker −0.047. Its effect on
  plain dense is mostly on *exact-term* (0.833 → 0.896), not paraphrase — it plants
  documentation vocabulary in the query, so it behaves as a keyword expander, which is
  BM25's job. Plain hybrid still beats it (0.845 vs 0.834) at +6 ms with no LLM call.
- **Ship the best variant** (rewrite retrieves, original question reranks). The best
  retrieval arm measured: +0.008 MRR over the reranker alone, and paraphrase +0.055 — the
  rewriter finally helping the slice it exists for. But +0.008 over 66 questions is about
  one question, bought with an extra LLM call on every query whose tokens come out of the
  same 200K/day budget as the generator. Not worth it.
- **Score the gate against the rewritten query.** Median top-1 rises 0.802 → 0.847: the
  rewrite puts the documentation's own words into the query and inflates every cosine,
  so the gate gets **looser**. On near-miss refusals that is exactly the wrong direction.
- **Score the gate against the original question.** Keeps the gate honest but refuses
  more answerable questions (up to 7/66 on hybrid): the rewrite retrieves chunks that are
  on-topic for the expansion and less similar to the literal question.

## Consequences

- ✅ The pipeline now has a rule that did not exist before: **rewrites steer, originals
  judge.** The generator answers what was asked; the reranker ranks against what was
  asked. With the identity rewriter both calls see the same string — verified: the
  reranker arm's MRR is 0.8674 before and after the change.
- ✅ Two latent bugs found by building a component that is then not shipped. The
  generator-prompt one would have produced answers to questions nobody asked.
- ✅ The ROADMAP's own hypothetical — "the query rewriter added latency for marginal gain,
  so I'd drop it in production" — is now a measured statement.
- ⚠️ Every retrieval-side addition so far has been partly **redundant with the others**:
  the reranker absorbed most of BM25's exact-term gain, and the rewriter duplicates BM25's
  vocabulary effect. The cheapest single change (hybrid, +6 ms) captures most of what is
  available; the rest is expensive.
- ⚠️ The gate problem is unsolved for any component that changes the query. If a rewriter
  ever ships, `floor` must be re-derived with the rule in `eval/floor-tuning.md`.
- 🔭 Revisit if the generator becomes cheap enough that one more call per query is free,
  or if a question set with far more paraphrase questions shows a larger gain than one
  question's worth.
