"""F2 — decide which candidate files are allowed to be embedded.

This runs *before* embedding, not at query time, because the index is the boundary:
once text is in the store it is retrievable, and no amount of query-side filtering
takes it back out. A file dropped here can be recovered by re-ingesting; a secret
that gets embedded cannot be un-embedded.

Every decision carries the rule that caused it, so `ingest --dry-run` can explain a
drop instead of just counting it. With no test suite, an explained drop is the only
way to notice a rule that is quietly too aggressive.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch

from infrachat.config import Config, SourceConfig
from infrachat.ingest.loader import CandidateFile


class DropReason(str, Enum):
    SECRET = "secret pattern"
    EXCLUDED = "exclude glob"
    EXTENSION = "extension not allowed"
    TOO_LARGE = "over max_file_bytes"


@dataclass(frozen=True)
class Verdict:
    """What happened to one file, and which rule decided it."""

    file: CandidateFile
    reason: DropReason | None = None   # None => kept
    pattern: str | None = None         # the specific rule that matched

    @property
    def kept(self) -> bool:
        return self.reason is None


def _matches(rel_path: str, pattern: str) -> bool:
    """Glob-match a source-relative POSIX path.

    Matched against the path both bare and with a leading slash, so `**/_print/**`
    catches `_print/x.md` at the source root as well as `a/_print/x.md` deeper in.
    """
    return fnmatch(rel_path, pattern) or fnmatch("/" + rel_path, pattern)


def _is_secret(file: CandidateFile, patterns: Iterable[str]) -> str | None:
    """Return the matching secret pattern, if any.

    Checked against the filename *and every directory segment*, so a `credentials/`
    directory is caught as well as a `credentials.yaml` file — and checked before
    extension rules, so a `secrets.md` is reported as a secret, not silently allowed
    for being markdown.
    """
    parts = file.rel_path.split("/")
    for pattern in patterns:
        if any(fnmatch(part, pattern) for part in parts):
            return pattern
    return None


def judge(file: CandidateFile, source: SourceConfig) -> Verdict:
    """Apply the rules in priority order and report the first that fires."""
    # 1. Secrets first — the hard rule, and the reason must be accurate even when a
    #    later rule would also have dropped the file.
    if (pattern := _is_secret(file, source.secret_patterns)):
        return Verdict(file, DropReason.SECRET, pattern)

    # 2. Explicitly excluded paths.
    for pattern in source.exclude_globs:
        if _matches(file.rel_path, pattern):
            return Verdict(file, DropReason.EXCLUDED, pattern)

    # 3. Allowed doc types only — this is what keeps images and binaries out.
    if file.suffix not in {e.lower() for e in source.include_ext}:
        return Verdict(file, DropReason.EXTENSION, file.suffix or "(no extension)")

    # 4. A guardrail against one pathological file, not a routine filter.
    if file.size > source.max_file_bytes:
        return Verdict(file, DropReason.TOO_LARGE, f"{file.size:,} > {source.max_file_bytes:,}")

    return Verdict(file)


def judge_all(files: Iterable[CandidateFile], cfg: Config) -> Iterator[Verdict]:
    """Judge every candidate against the rules of its own source."""
    for file in files:
        yield judge(file, cfg.source(file.source))


def kept(verdicts: Iterable[Verdict]) -> Iterator[CandidateFile]:
    """The files that survived — what the chunker actually reads."""
    for v in verdicts:
        if v.kept:
            yield v.file
