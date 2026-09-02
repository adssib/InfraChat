"""F1 — walk the configured doc trees and yield candidate files.

The loader decides *what exists*; `filter.py` decides *what is allowed*. Keeping them
apart means `ingest --dry-run` can show both numbers — files found vs. files kept —
and you can see at a glance whether a filter rule is too aggressive.

Nothing here reads file contents. Walking is cheap; opening 10k files is not.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from infrachat.config import Config, SourceConfig


@dataclass(frozen=True)
class CandidateFile:
    """One file found under a source root, before any filtering."""

    source: str      # source name, e.g. "kubernetes"
    path: Path       # absolute path on disk
    rel_path: str    # POSIX path relative to the SOURCE ROOT — becomes Chunk.source_doc
    size: int        # bytes, from the directory entry (no read)

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


class SourceMissingError(FileNotFoundError):
    """A configured source root is not on disk yet."""


def walk(source: SourceConfig, root: Path) -> Iterator[CandidateFile]:
    """Yield every regular file under one source root, in deterministic order.

    `rel_path` is relative to the source root, not the repo — so a chunk from the
    Kubernetes concepts tree cites `workloads/pods/_index.md`, not
    `corpus/kubernetes-website/content/en/docs/concepts/workloads/pods/_index.md`.

    Order is sorted, not filesystem order: chunk ids are derived from position, so a
    stable walk is what makes re-ingesting an unchanged corpus reproducible.
    """
    base = (root / source.path).resolve()
    if not base.is_dir():
        hint = f"\n    git clone --depth 1 --filter=blob:none --sparse {source.repo} corpus/..." if source.repo else ""
        raise SourceMissingError(
            f"source {source.name!r}: {base} does not exist — clone it first{hint}"
        )

    for path in sorted(base.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        yield CandidateFile(
            source=source.name,
            path=path,
            rel_path=path.relative_to(base).as_posix(),
            size=path.stat().st_size,
        )


def walk_all(cfg: Config, root: Path) -> Iterator[CandidateFile]:
    """Walk every configured source, in the order they appear in sources.yaml."""
    for source in cfg.sources:
        yield from walk(source, root)
