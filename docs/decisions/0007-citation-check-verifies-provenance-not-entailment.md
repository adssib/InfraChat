# ADR-0007: The citation check verifies provenance, not entailment

- **Status:** Accepted
- **Date:** 2026-09-22
- **Phase:** 1 (discovered by measurement)

## Context

[ADR-0001](0001-refuse-over-fabricate.md) arranges the system around two independent gates: a
retrieval-confidence floor, and a citation check that every `[source:doc]` tag in an answer was
actually shown to the model. The 30-question baseline run says the second gate works exactly as
specified — **citation validity measured 1.000 across 23 answers. Zero invented citations.**

And one should-refuse question was answered anyway.

`refuse-compose-run-app` — *"How do I write a docker-compose.yml to run my web app and database
together?"* — scored **0.765**, comfortably clear of the 0.55 floor. Three of its top five chunks
came from `docker:bake/compose-file.md`. The model returned a 730-character answer citing
`[docker:bake/compose-file]`: a real document, genuinely in context, correctly tagged. Gate 1
passed. Gate 2 passed. Both did what they were built to do.

The answer told the user to run `docker compose up`, and claimed `webapp` would wait for `db` to
be ready. Counted over the live index (`instr(text, ?) > 0` — **not** `LIKE`, where `_` is a
single-character wildcard that inflated the `depends_on` count from 0 to 56):

| Phrase | Chunks in the corpus |
|---|---|
| `docker compose up` | **0** |
| `service_healthy` | **0** |
| `depends_on` | **0** |

None of it came from the docs. The corpus slice is `content/manuals/build`, and
`bake/compose-file.md` is about consuming a Compose file **as a Bake build definition** — not
about Compose orchestration. The document is real, the citation is real, the claims are not in it.

The gates cannot catch this, because neither of them asks the question that would. Gate 1 asks
*was anything similar enough*. Gate 2 asks *was this document in front of the model*. Neither asks
*does this document say this*.

## Decision

**The citation check verifies provenance, not entailment.** A citation in this system means *this
document was in the model's context*. It does not mean *this document supports the sentence it is
attached to*, and the system has no mechanism that could make it mean that.

This is a permanent limit of the Phase 1 design, not a bug awaiting a fix. It is recorded here so
the project's guarantee is stated at its true size. **This does not supersede
[ADR-0001](0001-refuse-over-fabricate.md) — it bounds it.** Both gates remain correct, invariant,
and load-bearing; what changes is the claim made about what passing them proves.

## Alternatives considered

- **Raise the floor until this question refuses** — 0.765 sits well inside the band where real
  answerable questions live. Tuning the floor to exclude a near-miss buys refusal recall with
  false refusals, which [ADR-0001](0001-refuse-over-fabricate.md) already names as the failure
  mode that matters. The floor is not the thing that's wrong.
- **Lexical-overlap check between each sentence and its cited chunk** — cheap, and it probably
  *would* have caught this answer, since `docker compose up` appears nowhere in the corpus. But
  it approximates entailment badly in the other direction: a correct answer that paraphrases the
  source gets flagged, and a wrong answer that borrows the source's vocabulary gets through. It
  would trade a known limit for an unmeasured one.
- **Ship claim-level entailment checking now** — an NLI pass over each sentence against its cited
  chunk is the real fix (see below). It is also a second model, a second latency budget, and a
  second error rate, and it would be a **third gate**, not a change to gate 2 — the Phase 1 gates
  are invariant. Adding it without its own eval would mean trusting an unmeasured component to
  police a measured one.
- **Keep calling the system "grounded with citations" and say nothing** — the default in this
  space, and the reason the phrase has stopped meaning anything. Almost every RAG project claims
  it; very few can say what it covers. Being able to say exactly what it covers is worth more than
  the unqualified claim.

## Consequences

- ✅ **The guarantee is stated at its real size.** "Every claim carries a citation to a document
  that was actually retrieved" is true, checkable, and measured at 1.000 — and it is now on the
  record that this is a provenance property.
- ✅ **Found by measurement, not by reasoning.** No amount of reading the gate code surfaced this;
  running 30 questions and reading one answer did. A metric can sit at a perfect 1.000 while the
  failure lives in the space *between* the metrics.
- ⚠️ **Near-miss questions can be answered wrongly, confidently, and with a valid citation.** This
  class is not prevented by the design. Refusal recall must be read knowing that.
- ⚠️ **"Citation validity" must never be read as accuracy** — it measures where a tag came from,
  not whether the sentence is true. The name stays literal in [EVAL.md](../EVAL.md) for that
  reason.
- ⚠️ A narrow corpus slice **manufactures near-misses**: `bake/compose-file.md` carries all the
  right vocabulary for a question it does not answer. A broader corpus changes which documents
  do this, not whether any do.
- 🔭 Revisit if near-miss answers turn out to be a common class rather than a single case. The fix
  is **claim-level entailment checking** — an NLI pass scoring each sentence against the chunk it
  cites, refusing the answer when a sentence is unsupported — shipped as a third gate with its own
  measured false-refusal rate. **It is not scheduled.** It costs a second model and a latency
  budget Phase 1 does not have, and naming a fix is not the same as having one.
