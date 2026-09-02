# ADR-0004: SQLite as the chunk store; Postgres deferred to deployment

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 (forced), revisited at 5

## Context

Two holes appeared while reviewing the architecture, and they turn out to be the same hole.

1. **F5 says ingestion is "incremental per source" — with no mechanism.** To skip an unchanged
   file you need its content hash from last time; to re-ingest a changed one you need to find and
   delete the chunks it previously produced. Neither is possible without bookkeeping that
   survives between runs.
2. **From Phase 3 there are two indexes over the same chunks** — vectors in Chroma, postings in a
   keyword index. If each is built by independently re-walking the corpus, they can silently
   disagree, and "the same chunks, tokenized" becomes an aspiration rather than a fact.

Both dissolve if chunks live in **one** place that the indexes are *derived from*. So the question
isn't whether to add a store — it's which one.

The forces pulling on that choice:

- **Latency measurements must be clean.** [EVAL.md](../EVAL.md) commits to reporting p50/p95, and
  Phase 4's entire verdict is *"does the query rewriter earn its latency?"* Anything that puts a
  variable network hop under every retrieval contaminates the number the project exists to produce.
- **Phase 3's claim is specifically about BM25.** Whatever backs the keyword index has to rank
  with BM25, not something adjacent to it.
- **There is a portfolio argument for Postgres.** *"Hybrid retrieval over Postgres with pgvector"*
  is a stronger line than *"a SQLite file."* That's a real consideration, not a frivolous one.
- **Everything runs in a container with the data directory as a volume**, so "local" here means
  *in the same container*, not *on the developer's laptop specifically*.

## Decision

**SQLite is the chunk store** — one file holding `chunks` and the `files` manifest, and from
Phase 3 the FTS5 keyword index too. Chroma remains the vector store, keyed by `chunk_id`. Chunk
text is stored **once**, in SQLite; vector search returns ids and scores, and the chunk store
hydrates them.

The whole data directory (`infrachat.db` + the Chroma directory) is **a single Docker volume**.

**Postgres is not rejected — it is sequenced.** Migrating to Postgres + pgvector is a **Phase 5
deployment variant**, performed *after* the Phase 1–4 measurements are locked.

## Alternatives considered

- **Chroma only, no chunk store.** Chroma holds documents and metadata, so you *can* stash content
  hashes in chunk metadata and rebuild BM25 from stored documents at load. Zero new dependencies —
  and it uses a vector database as a relational store. The first query that isn't "find me similar
  vectors" (*which chunks came from this file?*) is awkward, and the answer to "where does a
  chunk's text live?" becomes "in two places."
- **Postgres (self-hosted or Neon) from Phase 1.** One store for chunks, manifest, vectors, and
  keyword search — genuinely tidier, and the CV line is real. Rejected for two reasons:
  - **It contaminates the measurements.** A hosted instance puts a network round-trip, and on
    free tiers a cold start after idle, underneath every retrieval — inside the p95 numbers that
    Phase 4's verdict depends on.
  - **Postgres core full-text search is `ts_rank`, not BM25.** True BM25 needs an extension
    (ParadeDB's `pg_search` or similar) whose availability on a managed provider must be verified.
    Approximating BM25 undercuts the one thing Phase 3 sets out to measure. SQLite's FTS5 ships
    `bm25()` in the box.
- **DuckDB / LanceDB.** Both plausible; neither beats SQLite for a small key-value-shaped chunk
  store, and each adds a dependency to learn for no measurable gain here.
- **Eval results in the database.** Rejected: four runs of ~30 questions is not a database's
  problem, and a committed JSONL file is readable by anyone reviewing the repo.

## Consequences

- ✅ **F5 becomes implementable.** Content-hash comparison makes re-ingest genuinely incremental,
  including deleting the chunks of documents that upstream removed.
- ✅ **The two indexes can't drift** — both are derived from the chunk store, and either can be
  rebuilt from it without re-walking the corpus.
- ✅ **Real BM25** in Phase 3, so the hybrid measurement means what it says.
- ✅ **Clean latency numbers** — no network hop under retrieval during the measured phases.
- ✅ **One volume** to mount, back up, or delete; no connection string, no secret, no cold start.
- ⚠️ **One extra local lookup per query** to hydrate chunk text. Microseconds, same process —
  named here so it isn't a surprise.
- ⚠️ **Two storage technologies** (SQLite + Chroma) instead of one. Accepted: collapsing them
  means Postgres, which costs the measurement integrity above.
- ⚠️ **SQLite's write concurrency is one writer.** Irrelevant here — ingestion is a single-process
  batch job and the query path is read-only — but it is the constraint that would bite first if
  the tool ever ingested concurrently.
- ⚠️ **The deployed demo can't use the volume.** Free-tier hosted Spaces have an ephemeral
  filesystem, so the image ships a pre-built read-only index and never ingests. Home-lab
  deployment keeps the volume.
- 🔭 **Revisit at Phase 5**, deliberately: migrate to Postgres + pgvector as a deployment variant
  once the measurements are locked. The `chunk_store:` and `store:` config keys exist so this is
  a swap, not a rewrite ([ADR-0002](0002-null-object-seams.md)). Revisit sooner only if the corpus
  grows past what a single SQLite file serves comfortably.
