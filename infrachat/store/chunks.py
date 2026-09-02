"""F5 — the chunk store: one SQLite file holding chunks, the manifest, and vectors.

ADR-0005. Three roles, one file, one connection:

    files        the ingest manifest — path → content hash → chunk count
    chunks       chunk text + provenance — **the single source of truth**
    vec_chunks   vectors keyed by chunk id (sqlite-vec `vec0` virtual table)

Because they share a connection, a vector search can JOIN the relational columns in one
query instead of round-tripping ids through Python.

The write API is deliberately one call per file — `replace_file` — because the delete and
the insert must be atomic. A crash between them would leave a document with no chunks and
a manifest row claiming it has some, and the next ingest would skip it as unchanged.
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import sqlite_vec

from infrachat.models import Chunk


def content_hash(text: str) -> str:
    """Stable digest of a file's raw bytes — the manifest's change detector."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _f32(vector: Sequence[float]) -> bytes:
    """sqlite-vec takes vectors as packed little-endian float32."""
    return struct.pack(f"{len(vector)}f", *vector)


class ChunkStore:
    """Owns the connection and the schema. One instance per process."""

    def __init__(self, path: Path, *, dim: int) -> None:
        self.path = path
        self.dim = dim
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)

        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id           INTEGER PRIMARY KEY,
                source       TEXT NOT NULL,
                path         TEXT NOT NULL,           -- relative to the source root
                content_hash TEXT NOT NULL,
                chunk_count  INTEGER NOT NULL,
                ingested_at  TEXT NOT NULL,
                UNIQUE (source, path)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id              TEXT PRIMARY KEY,     -- kubernetes:architecture/cgroups.md#2
                file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                source          TEXT NOT NULL,
                source_doc      TEXT NOT NULL,
                source_location TEXT NOT NULL,
                text            TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_file   ON chunks(file_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
            """
        )
        # vec0 is a virtual table: no foreign keys, so its rows are removed by hand.
        # distance_metric=cosine, not the default L2, so `1 - distance` IS cosine
        # similarity — the scale `retrieval.floor` was measured against. With L2 the
        # ranking would be identical (the embedder emits unit vectors, so
        # cos = 1 - L2²/2) but the floor number would silently mean something else.
        self.db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
            f"chunk_id TEXT PRIMARY KEY, embedding FLOAT[{self.dim}] distance_metric=cosine)"
        )
        self.db.commit()

    # ---- manifest (F5) --------------------------------------------------------

    def needs_reingest(self, source: str, rel_path: str, digest: str) -> bool:
        """True when the file is new or its content changed since the last ingest."""
        row = self.db.execute(
            "SELECT content_hash FROM files WHERE source = ? AND path = ?",
            (source, rel_path),
        ).fetchone()
        return row is None or row["content_hash"] != digest

    def replace_file(
        self,
        *,
        source: str,
        rel_path: str,
        digest: str,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]] | None = None,
    ) -> None:
        """Atomically swap one file's chunks and vectors for a new set.

        Stale rows go **before** new ones land, so an edited document never leaves
        orphans and a deleted one leaves nothing. Wrapped in a transaction because a
        crash between the two halves would desynchronise the manifest from the chunks.
        """
        if vectors is not None and len(vectors) != len(chunks):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")

        with self.db:  # BEGIN ... COMMIT, ROLLBACK on exception
            old = self.db.execute(
                "SELECT id FROM chunks WHERE source = ? AND source_doc = ?",
                (source, rel_path),
            ).fetchall()
            if old:
                ids = [r["id"] for r in old]
                self.db.executemany(
                    "DELETE FROM vec_chunks WHERE chunk_id = ?", [(i,) for i in ids]
                )
            self.db.execute(
                "DELETE FROM files WHERE source = ? AND path = ?", (source, rel_path)
            )  # cascades to chunks

            cur = self.db.execute(
                "INSERT INTO files (source, path, content_hash, chunk_count, ingested_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (source, rel_path, digest, len(chunks),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            file_id = cur.lastrowid

            self.db.executemany(
                "INSERT INTO chunks (id, file_id, source, source_doc, source_location, text)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(c.id, file_id, c.source, c.source_doc, c.source_location, c.text)
                 for c in chunks],
            )
            if vectors is not None:
                self.db.executemany(
                    "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                    [(c.id, _f32(v)) for c, v in zip(chunks, vectors)],
                )

    # ---- read path ------------------------------------------------------------

    def search(self, query_vector: Sequence[float], k: int) -> list[tuple[Chunk, float]]:
        """KNN over the vectors, joined to provenance in one query.

        Returns (Chunk, distance) — smaller distance is a closer match. Converting that
        to the [0,1] score the grounding gate reads is the retriever's job, not the
        store's: the store should not decide what "similar enough" means.
        """
        rows = self.db.execute(
            """
            SELECT c.id, c.source, c.source_doc, c.source_location, c.text, v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.id = v.chunk_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_f32(query_vector), k),
        ).fetchall()
        return [
            (Chunk(id=r["id"], text=r["text"], source=r["source"],
                   source_doc=r["source_doc"], source_location=r["source_location"]),
             r["distance"])
            for r in rows
        ]

    def hydrate(self, ids: Iterable[str]) -> list[Chunk]:
        """Look chunks up by id, for a retrieval arm that returns ids alone (BM25)."""
        ids = list(ids)
        if not ids:
            return []
        rows = self.db.execute(
            f"SELECT id, source, source_doc, source_location, text FROM chunks"
            f" WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
        by_id = {
            r["id"]: Chunk(id=r["id"], text=r["text"], source=r["source"],
                           source_doc=r["source_doc"], source_location=r["source_location"])
            for r in rows
        }
        return [by_id[i] for i in ids if i in by_id]   # preserve caller's ranking

    # ---- reporting ------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        q = lambda sql: self.db.execute(sql).fetchone()[0]
        return {
            "files": q("SELECT count(*) FROM files"),
            "chunks": q("SELECT count(*) FROM chunks"),
            "vectors": q("SELECT count(*) FROM vec_chunks"),
        }

    def per_source(self) -> dict[str, int]:
        return {
            r["source"]: r["n"]
            for r in self.db.execute(
                "SELECT source, count(*) AS n FROM chunks GROUP BY source ORDER BY source"
            )
        }

    def close(self) -> None:
        self.db.close()
