"""The data shapes the whole pipeline passes around.

Contract: docs/SPEC.md § Data shapes. These are plain dataclasses, not pydantic —
they are constructed internally, never parsed from untrusted input (that is what
config.py is for).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

# A source name is an open string, not a closed enum: adding a doc set (Ansible,
# Terraform, ...) is a sources.yaml entry, never a code change. Values are validated
# against the configured source names at load time, not here.
Source = str


def cite_tag(source: Source, source_doc: str) -> str:
    """The citation tag the LLM sees and echoes back, e.g.
    ``kubernetes:concepts/workloads/pods``.

    Deliberately the *document*, not the chunk: a reader wants to know which page a
    claim came from, not which 800-character window. Several chunks of one document
    therefore share a tag, and a tag resolves back to a document.
    """
    return f"{source}:{PurePosixPath(source_doc).with_suffix('').as_posix()}"


@dataclass
class Chunk:
    """One retrievable excerpt, with the provenance needed to cite it.

    ``id`` is stable and content-addressed by position, so re-ingesting an unchanged
    file produces the same ids. It is the primary key in every store.
    """

    id: str
    text: str
    source: Source
    source_doc: str        # path within the doc set, e.g. "content/manuals/build/multi-stage.md"
    source_location: str   # e.g. "L40-58" — provenance, required, never empty
    embedding: list[float] | None = None

    @staticmethod
    def make_id(source: Source, source_doc: str, ordinal: int) -> str:
        """Stable id: ``kubernetes:concepts/workloads/pods.md#3``."""
        return f"{source}:{source_doc}#{ordinal}"

    @property
    def tag(self) -> str:
        """The citation tag for this chunk's document."""
        return cite_tag(self.source, self.source_doc)


@dataclass
class Retrieved:
    """A chunk with the relevance score that surfaced it.

    ``score`` is whatever the *last* stage to rank wrote — dense similarity in Phase 1,
    fused rank in Phase 3, cross-encoder score in Phase 2. The grounding gate reads it,
    so the scale that populates it defines what ``floor`` means.
    """

    chunk: Chunk
    score: float


@dataclass
class Citation:
    """Where a claim came from. Renders as ``[kubernetes:concepts/workloads/pods]``."""

    source: Source
    source_doc: str
    source_location: str

    @property
    def tag(self) -> str:
        return cite_tag(self.source, self.source_doc)

    @classmethod
    def from_chunk(cls, chunk: Chunk) -> Citation:
        return cls(chunk.source, chunk.source_doc, chunk.source_location)


@dataclass
class Answer:
    """What the pipeline returns — an answer with citations, or a refusal.

    Invariant: ``grounded`` and ``citations`` move together. A grounded answer carries
    at least one citation; a refusal carries none. Build refusals with ``refuse()``
    rather than by hand, so the invariant holds in one place.
    """

    text: str
    citations: list[Citation] = field(default_factory=list)
    grounded: bool = True

    def __post_init__(self) -> None:
        if self.grounded and not self.citations:
            raise ValueError(
                "a grounded answer must carry at least one citation (F9) — "
                "use Answer.refuse() to return an ungrounded result"
            )
        if not self.grounded and self.citations:
            raise ValueError("a refusal must not carry citations")

    @classmethod
    def refuse(cls, reason: str) -> Answer:
        """The only way to construct an ungrounded result."""
        return cls(text=reason, citations=[], grounded=False)
