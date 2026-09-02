# ADR-0005: One SQLite file — chunks, manifest, vectors, and keyword index

- **Status:** Accepted — **supersedes [ADR-0004](0004-sqlite-chunk-store.md)**
- **Date:** 2026-08-30
- **Phase:** 1

## Context

[ADR-0004](0004-sqlite-chunk-store.md) put chunks and the file manifest in SQLite but kept
**Chroma** as the vector store, on the unexamined assumption that vector search needed a
dedicated database. That left two storage technologies, and it left the chunk store and the
index it feeds in different processes with no way to query across them.

Before building on it, the assumption was tested rather than trusted. A throwaway spike
answered three questions:

| Question | Result |
|---|---|
| Does `sqlite-vec` do real KNN? | Yes — `k=2` nearest-neighbour query returned correct ordering |
| Can chunk ids be readable strings, or must they be integers? | **TEXT primary keys supported** — `kubernetes:pods.md#3` works as the key everywhere, no integer-mapping layer |
| Can vector results join relational columns? | Yes — `join chunks c on c.id = v.chunk_id` in a single query |

The same spike settled the embedder: **`fastembed` pulls no torch** (223MB of site-packages,
ONNX only), and its `TextCrossEncoder` covers the Phase 2 reranker. Between them, the entire
storage and embedding stack fits in a small image with no server process.

## Decision

**One SQLite file holds everything**: `chunks`, the `files` manifest, vectors (`vec0` virtual
table via `sqlite-vec`), and from Phase 3 the FTS5 keyword index. **Chroma is dropped.**

ADR-0004's other two decisions stand unchanged: SQLite over a hosted database during the
measured phases, and Postgres + pgvector deferred to a Phase 5 deployment variant.

## Alternatives considered

- **Keep Chroma for vectors (ADR-0004 as written).** Two storage technologies, two things to
  keep consistent, and — the real cost — no way to filter or join a vector search against
  relational columns without pulling both sides into Python. Chroma also drags `onnxruntime`
  and friends into the image for a job the file already does.
- **Postgres + pgvector now.** Still rejected for the reasons in ADR-0004: a network hop under
  every retrieval lands inside the p95 numbers Phase 4 is judged on, and Postgres core FTS is
  `ts_rank`, not BM25.

## Consequences

- ✅ **One file, one Docker volume.** Back it up, delete it, or bake it into an image as a unit.
  No second store to keep consistent with the first.
- ✅ **Joins across vector and relational data**, which is what makes per-source filtering and
  provenance hydration a query rather than Python glue.
- ✅ **Readable primary keys** — `select * from chunks` shows `kubernetes:architecture/cgroups.md#2`,
  not `47`. With no test suite, legible storage is a debugging surface.
- ✅ **Smaller image, no server process** — matters for free-tier hosting and cold boot.
- ⚠️ **`sqlite-vec` is pre-1.0 (0.1.9).** The API may shift. This is the real risk, and it is
  accepted knowingly rather than discovered later.
- ⚠️ **One writer.** Irrelevant as designed — ingestion is a single batch process, the query path
  is read-only — but it is the constraint that bites first if ingestion is ever parallelised.
- ⚠️ **Extension loading must be available** in the host Python (`enable_load_extension`).
  Verified here; some distro-built Pythons disable it.
- 🔭 Revisit if `sqlite-vec` stalls or breaks: the `store:` seam means swapping back to Chroma is
  one file. Revisit deliberately at Phase 5 for the Postgres deployment variant.
