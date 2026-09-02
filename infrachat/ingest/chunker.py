"""F3 (second half) — split cleaned text into overlapping, citable chunks.

Chunking sets the ceiling on every later measurement: if the right sentence never lands
whole in a chunk, no reranker or fusion can recover it. So the strategy is a decision,
not a detail.

**Fixed-size windows, packed on paragraph boundaries.** Paragraphs are accumulated until
adding the next one would exceed `chunk.size`, then a window is emitted and the tail
`chunk.overlap` characters carry into the next one. A paragraph longer than the window is
hard-split as a last resort.

The alternative — splitting on markdown headings — keeps semantic sections intact but
produces wildly uneven chunks (a two-line section next to a 6KB one), which skews
similarity scores toward the short ones. Fixed windows keep scores comparable, which is
what the grounding floor depends on. Revisit once the eval can measure the difference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from infrachat.models import Chunk

_PARA_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class _Para:
    """A paragraph plus where it started, so a chunk can cite a line range."""

    text: str
    start_line: int   # 1-indexed, into the CLEANED text

    @property
    def end_line(self) -> int:
        return self.start_line + self.text.count("\n")


def _paragraphs(text: str) -> list[_Para]:
    """Split on blank lines, tracking line numbers as we go."""
    out: list[_Para] = []
    line = 1
    pos = 0
    for m in _PARA_BREAK.finditer(text):
        body = text[pos : m.start()]
        if body.strip():
            out.append(_Para(body.strip("\n"), line + body[: len(body) - len(body.lstrip("\n"))].count("\n")))
        line += text[pos : m.end()].count("\n")
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        out.append(_Para(tail.strip("\n"), line))
    return out


def _hard_split(para: _Para, size: int) -> list[_Para]:
    """A single paragraph bigger than the window — split on whitespace where possible.

    Whitespace alone is not enough. The corpus contains a 2001-character line holding the
    digits of pi (7 spaces in total), raw HTML tables indented with tabs, and an embedded
    mermaid diagram — none of which a word-splitter can break. Anything still oversized
    after the word pass is sliced at `size`, which is ugly but bounded; an unbounded chunk
    would blow past the embedder's context window and be silently truncated instead.
    """
    parts: list[str] = []
    cur = ""
    for w in para.text.split(" "):
        if cur and len(cur) + 1 + len(w) > size:
            parts.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        parts.append(cur)

    sliced: list[str] = []
    for part in parts:
        while len(part) > size:
            sliced.append(part[:size])
            part = part[size:]
        if part:
            sliced.append(part)

    # every part reports the parent's start line: the paragraph is one location
    return [_Para(p, para.start_line) for p in sliced]


def chunk_text(
    text: str, *, source: str, source_doc: str, size: int, overlap: int
) -> list[Chunk]:
    """Cleaned document text → chunks with stable ids and provenance.

    `source_location` is a line range **into the cleaned text**, not the raw file — the
    cleaner removed frontmatter and shortcodes, so the numbers will not line up with the
    original. It is provenance for debugging retrieval, not a file offset to seek to; the
    citation a reader follows is the document tag.
    """
    paras: list[_Para] = []
    for p in _paragraphs(text):
        limit = size - overlap
        paras.extend(_hard_split(p, limit) if len(p.text) > limit else [p])

    windows: list[list[_Para]] = []
    window: list[_Para] = []

    def carry_tail() -> list[_Para]:
        """Trailing paragraphs that fit inside `overlap` — the context bridge."""
        tail: list[_Para] = []
        total = 0
        for p in reversed(window):
            if total + len(p.text) > overlap:
                break
            tail.insert(0, p)
            total += len(p.text) + 2
        return tail

    length = 0
    for para in paras:
        if window and length + len(para.text) + 2 > size:
            windows.append(window)
            # Carry context forward only if the next paragraph still fits alongside it.
            # `size` is the size of the whole chunk, not of its new content — otherwise a
            # chunk silently grows to size + overlap and the number in config means nothing.
            window = carry_tail()
            length = sum(len(p.text) + 2 for p in window)
            if length + len(para.text) + 2 > size:
                window, length = [], 0
        window.append(para)
        length += len(para.text) + 2
    if window:
        windows.append(window)

    # A window shorter than `overlap` is already contained in its neighbour in full, so it
    # carries no new information — only a short, noisy embedding. Absorb it backwards.
    merged: list[list[_Para]] = []
    for w in windows:
        body_len = sum(len(p.text) + 2 for p in w)
        prev_len = sum(len(p.text) + 2 for p in merged[-1]) if merged else 0
        if merged and body_len < overlap and prev_len + body_len <= size:
            merged[-1].extend(p for p in w if p not in merged[-1])
        else:
            merged.append(w)

    chunks: list[Chunk] = []
    for ordinal, w in enumerate(merged):
        chunks.append(
            Chunk(
                id=Chunk.make_id(source, source_doc, ordinal),
                text="\n\n".join(p.text for p in w),
                source=source,
                source_doc=source_doc,
                source_location=f"L{w[0].start_line}-{w[-1].end_line}",
            )
        )

    return chunks
