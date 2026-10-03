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
from infrachat.answer import llm
from infrachat.config import Config, load_config
from infrachat.ingest.chunker import chunk_text
from infrachat.ingest.cleaner import for_strategy
from infrachat.ingest.filter import judge, DropReason
from infrachat.ingest.loader import SourceMissingError, walk
from infrachat.models import Chunk
from infrachat.pipeline import Deps, answer_query, retrieve
from infrachat.retrieve.dense import DenseRetriever
from infrachat.retrieve.hybrid import HybridRetriever
from infrachat.retrieve.rerank import build as build_reranker
from infrachat.retrieve.rewrite import build as build_rewriter
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

    # Everything downstream of the raw bytes that affects what gets stored.
    ingest_params = (f"chunk={cfg.chunk.size}/{cfg.chunk.overlap}"
                     f"|embedder={cfg.embedder.model}")

    started = time.monotonic()
    totals = dict(scanned=0, kept=0, skipped=0, chunks=0, dropped=0)

    for source in sources:
        cleaner = for_strategy(source.clean)
        source_params = f"{ingest_params}|clean={source.clean}"
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
            # Any change to these re-chunks or re-embeds the file; see content_hash.
            digest = content_hash(raw, params=source_params)

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

            if store is not None:
                # Record the manifest row even when a file yields no chunks — Hugo
                # section stubs are pure frontmatter and clean to nothing. Without the
                # row, `needs_reingest` sees no record and re-reads them on every run
                # forever, and the manifest stops being a truthful list of what ingest
                # has seen.
                vectors = embedder.embed_documents([c.text for c in chunks]) if chunks else []
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


def _open_index(cfg: Config, root: Path) -> tuple[ChunkStore, object]:
    """Open the built index, or explain how to build it."""
    embedder = embed.build(cfg.embedder.model)
    db_path = cfg.db_path if cfg.db_path.is_absolute() else root / cfg.db_path
    if not db_path.exists():
        raise SystemExit(f"no index at {db_path}\n  build it first:  infrachat ingest -c <config>")
    return ChunkStore(db_path, dim=embedder.dim), embedder


def _build_deps(cfg: Config, store: ChunkStore, embedder, *, with_llm: bool) -> Deps:
    """Assemble the seams from config.

    Phase 1 always uses the null objects. Turning a later-phase toggle on is refused
    loudly rather than silently ignored — a config that says `rerank.enabled: true` while
    the pipeline quietly passes through would make an eval run mislabel its own results.
    """
    return Deps(
        rewriter=(build_rewriter(cfg.rewrite, cfg.require_llm()) if cfg.rewrite.enabled
                  else build_rewriter(cfg.rewrite, None)),
        retriever=(HybridRetriever(store, embedder) if cfg.retrieval.hybrid.enabled
                   else DenseRetriever(store, embedder)),
        reranker=build_reranker(cfg.rerank),
        llm=llm.build(cfg.require_llm()) if with_llm else None,
    )


class _TracePrinter:
    """`ask --trace`: the event stream the UI will render, printed as it arrives.
    Reasoning is dimmed; the answer streams as an unverified draft until gate 2 rules."""

    DIM, GREEN, AMBER, RESET = ("\033[2m", "\033[32m", "\033[33m", "\033[0m") \
        if sys.stdout.isatty() else ("", "", "", "")

    def __init__(self) -> None:
        self.streaming: str | None = None   # "reasoning" | "token" while a stream is open

    def _end_stream(self) -> None:
        if self.streaming:
            print(self.RESET)
            self.streaming = None

    def __call__(self, e) -> None:
        d = e.data
        if e.type in ("llm.reasoning", "llm.token"):
            kind = "reasoning" if e.type == "llm.reasoning" else "token"
            if self.streaming != kind:
                self._end_stream()
                label = "  scratchpad  " if kind == "reasoning" else "  draft       "
                print(f"{self.DIM if kind == 'reasoning' else ''}{label}", end="")
                self.streaming = kind
            print(d["delta"].replace("\n", " "), end="", flush=True)
            return
        self._end_stream()
        t = e.type
        if t == "start":
            c = d["config"]
            print(f"\n  ? {d['question']}   [hybrid={c['hybrid']} rerank={c['rerank']} "
                  f"rewrite={c['rewrite']} floor={c['floor']}]")
        elif t == "rewrite":
            print(f"  ✓ rewrite     {'→ ' + d['query'] if d['changed'] else 'unchanged'}")
        elif t == "embed":
            print(f"  ✓ embed       {d['ms']:.0f} ms")
        elif t == "retrieve.dense":
            print(f"  ✓ dense       {d.get('count', len(d.get('hits', [])))} chunks · {d['ms']:.0f} ms")
        elif t == "retrieve.keyword":
            print(f"  ✓ bm25        {d['count']} chunks · {d['ms']:.0f} ms")
        elif t == "fuse":
            promoted = sum(1 for h in d["hits"] if h["dense_rank"] is None or h["dense_rank"] > h["rank"])
            print(f"  ✓ fuse (rrf)  top {len(d['hits'])} · {promoted} lifted by keyword")
        elif t == "rerank":
            what = f"{len(d['moves'])} moved · {d['ms']:.0f} ms" if d["active"] else "off (pass-through)"
            print(f"  ✓ rerank      {what}")
            for h in d["hits"]:
                print(f"      {h['rank']}. {h['score']:.3f}  {h['tag']}  {self.DIM}{h['lines']}{self.RESET}")
        elif t == "gate.floor":
            mark = f"{self.GREEN}✓" if d["passed"] else f"{self.AMBER}⦸"
            print(f"  {mark} gate 1{self.RESET}      top-1 {d['top_score']:.3f} vs floor {d['floor']}")
        elif t == "prompt":
            print(f"  ◌ generating  ~{d['tokens_est']} prompt tokens")
        elif t == "gate.citations":
            mark = f"{self.GREEN}✓" if d["passed"] else f"{self.AMBER}⦸"
            extra = f" · invented {d['invented']}" if d["invented"] else ""
            print(f"  {mark} gate 2{self.RESET}      cited {d['cited'] or 'nothing'}{extra}")
        elif t == "answer":
            print(f"\n{d['text']}\n")
            for c in d["citations"]:
                print(f"  [{c['n']}] {c['tag']}  {self.DIM}{c['doc']} · {c['lines']}{self.RESET}")
        elif t == "refusal":
            print(f"\n  {self.AMBER}⦸ refused at {d['gate']}{self.RESET}: {d['detail']}\n  {d['reason']}")
        elif t == "done":
            u = d.get("usage") or {}
            rl = d.get("ratelimit") or {}
            tokens = f" · {u.get('total_tokens')} tokens" if u else ""
            left = f" · {rl.get('remaining-tokens')} left this minute" if rl else ""
            print(f"\n  {self.DIM}{d['ms_total'] / 1000:.2f} s{tokens}{left}{self.RESET}")


def cmd_ask(args: argparse.Namespace) -> int:
    """One question → a cited answer, or one of the two refusals."""
    question = " ".join(args.question).strip()
    if not question:
        print("error: ask what?  e.g. infrachat ask \"what is a Pod?\"", file=sys.stderr)
        return 2

    cfg = load_config(args.config)
    root = Path(args.config).resolve().parent
    store, embedder = _open_index(cfg, root)
    try:
        deps = _build_deps(cfg, store, embedder, with_llm=not args.retrieval_only)

        if args.retrieval_only:
            r = retrieve(question, cfg, deps)
            print(f"\n{r.decision}\n")
            for i, hit in enumerate(r.hits, 1):
                preview = " ".join(hit.chunk.text.split())[:96]
                print(f"  {i}. {hit.score:.3f}  {hit.chunk.tag}")
                print(f"      {hit.chunk.source_doc} · {hit.chunk.source_location}")
                print(f"      {preview}...")
            if not r.decision.passed:
                print(f"\n  → would refuse: {cfg.refusal_message()}")
            return 0

        if args.trace:
            from infrachat import trace
            trace.answer(question, cfg, deps, _TracePrinter())
            return 0

        answer = answer_query(question, cfg, deps)
        print()
        print(answer.text)
        if answer.citations:
            print()
            for c in answer.citations:
                print(f"  [{c.tag}]  {c.source_doc} · {c.source_location}")
        return 0
    finally:
        store.close()


def cmd_eval(args: argparse.Namespace) -> int:
    """Run the fixed question set and write a comparable results file."""
    from infrachat import evaluate

    cfg = load_config(args.config)
    root = Path(args.config).resolve().parent
    store, embedder = _open_index(cfg, root)
    try:
        deps = _build_deps(cfg, store, embedder, with_llm=not args.retrieval_only)
        summary = evaluate.run(cfg, deps, root=root, progress=not args.quiet, resume=args.resume)
        if summary.get("reused"):
            print(f"resumed: kept {summary['reused']} completed question(s) from the existing run")
        if summary.get("daily_cap_hit"):
            print("stopped calling the API after hitting the daily token cap — "
                  "run again with --resume once tokens free up")
        print()
        print(evaluate.format_summary(summary))
        return 0
    finally:
        store.close()


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the HTTP API. The Gradio page was retired (docs/DEMO-PLAN.md); the Litestar
    API that replaces it is the next milestone. Until it lands this says so and exits 2,
    rather than failing with an import error."""
    print("infrachat: `serve` is being rebuilt as a Litestar API (docs/DEMO-PLAN.md § 3).\n"
          "Until then: `infrachat ask` for answers, `ask --retrieval-only` for retrieval.",
          file=sys.stderr)
    return 2


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

    ask = subs.add_parser("ask", help="ask one question")
    ask.add_argument("question", nargs="+")
    ask.add_argument("-c", "--config", default="config.yaml")
    ask.add_argument("--retrieval-only", action="store_true",
                     help="show what retrieval found and what the gate decided; no LLM, no API key")
    ask.add_argument("--trace", action="store_true",
                     help="print every pipeline step as it happens, and stream the model's output")
    ask.set_defaults(func=cmd_ask)

    ev = subs.add_parser("eval", help="run the fixed question set")
    ev.add_argument("-c", "--config", default="config.yaml")
    ev.add_argument("--retrieval-only", action="store_true",
                    help="score retrieval only; no LLM, no API key")
    ev.add_argument("--quiet", action="store_true", help="no per-question progress")
    ev.add_argument("--resume", action="store_true",
                    help="keep completed questions from the existing run file; re-run only errored ones")
    ev.set_defaults(func=cmd_eval)

    sv = subs.add_parser("serve", help="run the HTTP API (being rebuilt; exits 2 for now)")
    sv.add_argument("-c", "--config", default="config.yaml")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
