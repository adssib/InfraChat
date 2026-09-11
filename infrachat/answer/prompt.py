"""F7 — build the grounded prompt: the only context the generator is allowed to use.

Two things in here are **contracts**, not wording, and changing either breaks the
citation check downstream (docs/SPEC.md § Format contracts):

    NOT_IN_DOCS         the exact sentinel the model emits when the excerpts don't answer
    [source:location]   the citation tag it appends to each claim

Everything else — tone, ordering, how the rules are phrased — is tunable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from infrachat.models import Retrieved

#: The system prompt lives in `infrachat/prompts/system.txt`, not in this file.
#: It is *content*, edited far more often than the code around it, and keeping it in a
#: plain file means a prompt change is a readable one-file diff rather than a Python edit.
#: Loaded relative to __file__ so it works from any working directory and inside the
#: container, and read once at import.
#:
#: ⚠️ The prompt is an experiment variable. Editing it changes eval results exactly the
#: way changing the embedder or the chunk size does — see SYSTEM_PROMPT_SHA below.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()

#: Short digest of the prompt actually in use, so a run can record which one produced it.
SYSTEM_PROMPT_SHA = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def build_prompt(query: str, hits: list[Retrieved], max_chunks: int | None = None) -> str:
    """Render retrieved chunks into the user half of the prompt.

    Each excerpt is headed by the **exact tag** the model should echo, so citations can be
    matched back mechanically rather than parsed out of prose. The file path and line
    range follow in parentheses: useful to a human reading the prompt while debugging,
    and ignored by the matcher.

    `max_chunks` caps context size — and therefore cost. It is applied here rather than
    at retrieval so the gate still sees the full ranked list when deciding to refuse.
    """
    selected = hits[:max_chunks] if max_chunks else hits

    blocks = []
    for hit in selected:
        c = hit.chunk
        blocks.append(f"[{c.tag}] ({c.source_doc}, {c.source_location})\n{c.text}")

    context = "\n\n---\n\n".join(blocks)
    return f"Documentation excerpts:\n\n{context}\n\nQuestion: {query}\n\nAnswer:"


def offered_tags(hits: list[Retrieved], max_chunks: int | None = None) -> set[str]:
    """The tags the model was actually shown.

    The citation check validates against this, not against the whole index: a tag that is
    real but was never in context means the model recalled it rather than read it, which
    is exactly the ungrounded answer F9 exists to reject.
    """
    return {h.chunk.tag for h in (hits[:max_chunks] if max_chunks else hits)}
