# Architecture Decision Records (ADRs)

Each file records **one decision**: the context that forced it, the options weighed, the choice,
and what it costs. This trail is deliberate — it shows *how* the system was reasoned about, not
just how it ended up.

**Adding one:** copy [`0000-adr-template.md`](0000-adr-template.md) to the next number, fill it in,
and add a row below. When a decision changes, write a *new* ADR and mark the old one
**Superseded** — never rewrite history.

| ADR | Decision | Phase | Status |
|---|---|---|---|
| [0001](0001-refuse-over-fabricate.md) | Refuse over fabricate — two independent gates, floor and citation | 1 | Accepted |
| [0002](0002-null-object-seams.md) | Every optional component is a config-toggled null object | 1 | Accepted |
| [0003](0003-eval-harness-is-phase-1.md) | Build the eval harness in Phase 1, before any optional component | 1 | Accepted |
| [0004](0004-sqlite-chunk-store.md) | SQLite as the chunk store; Postgres deferred to deployment | 1 | Accepted |

**Start with [ADR-0001](0001-refuse-over-fabricate.md)** — it's the decision the rest of the
system is arranged around.

## Not yet decided

These are real choices, but nothing has been built yet and **an ADR written before the decision is
actually forced is a guess, not a record.** Each gets written when its phase lands — with the
measurement or the constraint that settled it.

| Decision | Forced in | What will settle it |
|---|---|---|
| **Chunking strategy** — fixed-size windows vs. markdown-heading-aware splitting | Phase 1 | the real shape of the two doc trees, once walked. It silently caps every later component's ceiling ([ARCHITECTURE § Assumptions](../ARCHITECTURE.md#assumptions--risks-on-the-record)). |
| **Corpus refresh** — stay on a pinned clone, or add clone-and-refresh | Phase 1 | whether stale answers actually bite during the first eval runs |
| **Postgres migration** — move the chunk store and vectors to Postgres/pgvector for the public deploy | Phase 5 | whether the hosted demo needs it, once the measurements are locked ([ADR-0004](0004-sqlite-chunk-store.md) sequences this deliberately) |
| **LLM provider + model** — which OpenAI-compatible endpoint, hosted or local | Phase 1 | cost and refusal-obedience on the real question set |
| **Two-stage retrieval sizing** — `retrieve_n` = 20, `k` = 5 | Phase 2 | reranker latency vs. the hit-rate/MRR delta |
| **Fusion method** — reciprocal rank fusion vs. score-weighted | Phase 3 | whether the two arms' scores turn out comparable at all |
| **Whether the query rewriter ships** | Phase 4 | the latency it adds vs. the quality it buys. **If it doesn't earn its place, the ADR records removing it** — with the numbers. |
