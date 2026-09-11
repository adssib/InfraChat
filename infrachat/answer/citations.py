"""F9 — the citation check: the second refusal, and the one that catches what the floor
cannot.

The retrieval floor (F8) asks *was anything similar enough*. This asks *did the model
actually answer from what it was shown*. They fail independently, which is the point:
the "how do I bake sourdough bread?" case clears the floor at 0.652 because Docker has a
build tool called **Bake** — the chunk genuinely is similar. Only reading the excerpts
reveals it is about the wrong subject.

Two rejections happen here:

    NOT_IN_DOCS          the model said the excerpts don't answer the question
    no matchable tag     the model answered without grounding it in what it was shown

The second is the backstop that does **not** depend on the model obeying an instruction.
A model that ignores the NOT_IN_DOCS rule still has to produce a citation, and a citation
it invented will not match a tag that was in context.
"""

from __future__ import annotations

import re

from infrachat.models import Answer, Citation, Retrieved

#: The exact sentinel from docs/SPEC.md § Format contracts.
NOT_IN_DOCS = "NOT_IN_DOCS"

#: The Gate-2 refusal. Distinct from the Gate-1 message, which names the doc sets — this
#: one is about the *answer* being ungrounded, not about the corpus lacking the subject.
INSUFFICIENT_GROUNDING = "Insufficient grounding to answer."

#: Any bracketed span. The tag is located *inside* it rather than parsed out of it.
_BRACKETED = re.compile(r"\[([^\]]+)\]")


def parse_tags(text: str, offered: set[str]) -> list[str]:
    """Which of the `offered` tags the completion cites, in order of first appearance.

    Deliberately **recognition, not parsing**. The first version matched a strict
    `[source:doc]` shape and rejected a correctly grounded answer that cited
    `[Source: docker:building/multi-stage L1-21]` — a prefix and a line range the
    instruction had arguably invited.

    Because the valid tags are known exactly (they were printed in the prompt), searching
    for them inside a bracketed span is both more tolerant of formatting and *stricter*
    about content: an invented tag is not in `offered`, so no amount of creative
    formatting smuggles one through. Brackets are still required — a tag appearing in
    running prose is not a citation.
    """
    seen: dict[str, None] = {}
    for span in _BRACKETED.findall(text):
        for tag in offered:
            if tag in span:
                seen.setdefault(tag, None)
    return list(seen)


#: A tag-shaped string: `word:path`. Used only to spot citations the model INVENTED —
#: `parse_tags` deliberately cannot see those, because it only recognises valid tags.
_TAG_SHAPED = re.compile(r"\b([A-Za-z0-9_.-]+:[A-Za-z0-9_./-]+)")


def parse_tag_candidates(text: str) -> list[str]:
    """Every tag-shaped string inside a bracketed span, valid or not.

    `parse_tags` answers "which real sources did it cite"; this answers "what did it
    *claim* to cite". The eval needs the second to measure citation validity — an answer
    that cites one real document and one invented one is grounded but partly fabricated,
    and reading `Answer.citations` back would score that 100% by construction, since
    `verify` has already dropped the invented one.
    """
    seen: dict[str, None] = {}
    for span in _BRACKETED.findall(text):
        for cand in _TAG_SHAPED.findall(span):
            seen.setdefault(cand, None)
    return list(seen)


def _said_not_in_docs(text: str) -> bool:
    """Lenient about wrapping, strict about intent.

    The contract asks for exactly `NOT_IN_DOCS`, but models wrap sentinels in politeness
    or code fences. Accepting the sentinel when it is the whole substantive response
    avoids turning an obedient refusal into a confusing uncited-answer rejection —
    while a completion that merely *mentions* it mid-sentence is not treated as one.
    """
    stripped = text.strip().strip("`*_ \n")
    return stripped == NOT_IN_DOCS or stripped.startswith(NOT_IN_DOCS)


def verify(completion: str, hits: list[Retrieved], offered: set[str]) -> Answer:
    """Turn a raw completion into an Answer, or a refusal.

    `offered` is the set of tags the model was actually shown (prompt.offered_tags), not
    every tag in the index. A citation that is real but was never in context means the
    model recalled it rather than read it — `kubernetes:workloads/pods` is exactly the
    kind of well-known path a model will produce from memory.
    """
    if _said_not_in_docs(completion):
        return Answer.refuse(INSUFFICIENT_GROUNDING)

    cited = parse_tags(completion, offered)
    if not cited:
        # Either no citation at all, or every citation was invented.
        return Answer.refuse(INSUFFICIENT_GROUNDING)

    # Map each surviving tag back to a chunk that carried it, for the Citation record.
    by_tag: dict[str, Retrieved] = {}
    for hit in hits:
        by_tag.setdefault(hit.chunk.tag, hit)

    return Answer(
        text=completion.strip(),
        citations=[Citation.from_chunk(by_tag[t].chunk) for t in cited if t in by_tag],
        grounded=True,
    )
