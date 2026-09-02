"""Command-line entry point: ingest | ask | eval | serve.

Subcommands rather than flags so `serve` maps cleanly onto a container entrypoint.

Only `ingest` is implemented; the rest announce themselves as unbuilt rather than
failing obscurely. A student project that lies about what works is worse than one with
gaps.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from infrachat import embed
from infrachat.config import Config, load_config
from infrachat.ingest.chunker import chunk_text
from infrachat.ingest.cleaner import for_strategy
from infrachat.ingest.filter import judge, DropReason
from infrachat.ingest.loader import SourceMissingError, walk
from infrachat.models import Chunk
from infrachat.store.chunks import ChunkStore, content_hash


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n}"


def cmd_ingest(args: argparse.Namespace) -> int:
    """Walk → filter → clean → chunk → embed → store, skipping unchanged files."""
    cfg: Config = load_config(args.config)
    root = Path(args.config).resolve().parent
    sources = [s for s in cfg.sources if not args.source or s.name == args.source]
    if not sources:
        print(f"error: no source named {args.source!r}; "
              f"configured: {sorted(cfg.source_names)}", file=sys.stderr)
        return 2

    store = None
    embedder = None
    if not args.dry_run:
        embedder = embed.build(cfg.embedder.model)
        # cfg.db_path, not cfg.data_dir — passing the directory made SQLite create a
        # database file literally named `data` at the repo root, alongside `data-wal`
        # and `data-shm`, none of which `.gitignore`'s `data/` rule matches.
        db_path = cfg.db_path if cfg.db_path.is_absolute() else root / cfg.db_path
        store = ChunkStore(db_path, dim=embedder.dim)

    started = time.monotonic()
    totals = dict(scanned=0, kept=0, skipped=0, chunks=0, dropped=0)

    for source in sources:
        cleaner = for_strategy(source.clean)
        print(f"\n{source.name}  ({source.path})")
        try:
            candidates = list(walk(source, root))
        except SourceMissingError as e:
            print(f"  {e}", file=sys.stderr)
            return 1

        drops: dict[str, int] = {}
        kept = skipped = chunked = 0

        for cand in candidates:
            verdict = judge(cand, source)
            if not verdict.kept:
                drops[verdict.reason.value] = drops.get(verdict.reason.value, 0) + 1
                continue
            kept += 1

            raw = cand.path.read_text(errors="replace")
            digest = content_hash(raw)

            if store is not None and not store.needs_reingest(source.name, cand.rel_path, digest):
                skipped += 1
                continue

            chunks: list[Chunk] = chunk_text(
                cleaner.clean(raw),
                source=source.name,
                source_doc=cand.rel_path,
                size=cfg.chunk.size,
                overlap=cfg.chunk.overlap,
            )
            chunked += len(chunks)

            if store is not None and chunks:
                vectors = embedder.embed_documents([c.text for c in chunks])
                store.replace_file(source=source.name, rel_path=cand.rel_path,
                                   digest=digest, chunks=chunks, vectors=vectors)

        totals["scanned"] += len(candidates)
        totals["kept"] += kept
        totals["skipped"] += skipped
        totals["chunks"] += chunked
        totals["dropped"] += sum(drops.values())

        print(f"  scanned {len(candidates)} · kept {kept} · skipped {skipped} (unchanged) "
              f"· chunked {chunked}")
        for reason, n in sorted(drops.items(), key=lambda kv: -kv[1]):
            print(f"    dropped {n:>4}  {reason}")

    elapsed = time.monotonic() - started
    print()
    if args.dry_run:
        print(f"DRY RUN — nothing written. {totals['kept']} files would produce "
              f"{totals['chunks']} chunks ({elapsed:.1f}s)")
    else:
        s = store.stats()
        db = store.path
        print(f"{db}: {s['files']} files · {s['chunks']} chunks · {s['vectors']} vectors "
              f"({_human(db.stat().st_size)}) in {elapsed:.1f}s")
        print(f"  per source: {store.per_source()}")
        store.close()
    return 0


def _unbuilt(name: str, after: str):
    def run(args: argparse.Namespace) -> int:
        print(f"`infrachat {name}` is not built yet — it lands after {after}.\n"
              f"Working today: infrachat ingest [--dry-run]", file=sys.stderr)
        return 2
    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="infrachat",
                                description="Ask the Kubernetes and Docker docs — with citations, or a refusal.")
    subs = p.add_subparsers(dest="command", required=True)

    ing = subs.add_parser("ingest", help="build the index from the configured sources")
    ing.add_argument("-c", "--config", default="config.yaml")
    ing.add_argument("--source", help="ingest only this source")
    ing.add_argument("--dry-run", action="store_true",
                     help="walk, filter and chunk, but write nothing and load no model")
    ing.set_defaults(func=cmd_ingest)

    for name, help_text, after in [
        ("ask", "ask one question", "the retriever and the grounding gate"),
        ("eval", "run the fixed question set", "`ask`"),
        ("serve", "run the demo UI", "`ask`"),
    ]:
        sp = subs.add_parser(name, help=help_text)
        sp.add_argument("-c", "--config", default="config.yaml")
        sp.add_argument("question", nargs="*")
        sp.set_defaults(func=_unbuilt(name, after))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
