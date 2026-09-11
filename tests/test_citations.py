"""F9 — the citation check. This is the gate that catches an ungrounded answer the
retrieval floor cannot, and every failure here is silent by construction: a fabricated
answer with a plausible-looking tag renders exactly like a real one.

The critical case is the last one a reviewer expects: a citation naming a document that
genuinely exists but was NOT in the prompt's context. That is the model reciting
`kubernetes:workloads/pods` from memory, not reading the excerpt it was given — and it
must be refused, not rendered with a citation that happens to resolve.

No LLM is involved: `verify()` is a pure function over a completion string.
"""

import pytest

from infrachat.answer.citations import INSUFFICIENT_GROUNDING, verify
from infrachat.answer.prompt import offered_tags
from infrachat.models import Chunk, Retrieved


def shown(source: str, source_doc: str) -> Retrieved:
    """One chunk that was actually put in the prompt."""
    chunk = Chunk(
        id=Chunk.make_id(source, source_doc, 0),
        text="Use --mount=type=secret to expose a secret to a single build step.",
        source=source,
        source_doc=source_doc,
        source_location="L40-58",
    )
    return Retrieved(chunk=chunk, score=0.71)


CONTEXT = [shown("docker", "building/secrets.md")]   # tag: docker:building/secrets
IN_CONTEXT = "docker:building/secrets"
REAL_BUT_NOT_SHOWN = "kubernetes:workloads/pods"     # exists in the index, never offered


def test_citing_a_real_document_that_was_not_in_context_is_refused() -> None:
    completion = f"Pods share a network namespace [{REAL_BUT_NOT_SHOWN}]."

    answer = verify(completion, CONTEXT, offered_tags(CONTEXT))

    assert not answer.grounded, "a tag the model was never shown was accepted as grounding"
    assert answer.text == INSUFFICIENT_GROUNDING
    assert answer.citations == []


@pytest.mark.parametrize(
    "completion",
    [
        "NOT_IN_DOCS",
        "`NOT_IN_DOCS`",
        "```\nNOT_IN_DOCS\n```",
        "**NOT_IN_DOCS**",
        "NOT_IN_DOCS — the excerpts are about Docker Bake, not baking bread.",
    ],
)
def test_the_refusal_sentinel_is_honoured_however_the_model_wraps_it(completion: str) -> None:
    # A wrapped sentinel that is not recognised becomes an "uncited answer" rejection:
    # still a refusal, but the logged reason is wrong and the obedient model looks broken.
    answer = verify(completion, CONTEXT, offered_tags(CONTEXT))

    assert not answer.grounded
    assert answer.text == INSUFFICIENT_GROUNDING


def test_an_answer_with_no_citation_at_all_is_refused() -> None:
    completion = "Run kubectl create secret generic to store the credentials."

    answer = verify(completion, CONTEXT, offered_tags(CONTEXT))

    assert not answer.grounded, "an uncited answer rendered as an answer (invariant 4)"
    assert answer.text == INSUFFICIENT_GROUNDING


def test_an_invented_citation_alongside_a_real_one_is_dropped() -> None:
    completion = (
        f"Build secrets are mounted per step [{IN_CONTEXT}] "
        f"and never land in the image layers [{REAL_BUT_NOT_SHOWN}]."
    )

    answer = verify(completion, CONTEXT, offered_tags(CONTEXT))

    assert answer.grounded
    assert [c.tag for c in answer.citations] == [IN_CONTEXT], "an unoffered tag survived"
