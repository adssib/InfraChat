"""F16 — the demo UI: one Gradio page over `pipeline.answer_from()`.

**Thin by contract.** This module renders; it does not decide. There is no retrieval
logic, no gate logic and no prompt building in here — it calls `pipeline.retrieve()` and
`pipeline.answer_from()` and formats what comes back. If a feature needs a decision made
in this file, it belongs behind a seam in the pipeline instead (ADR-0002).

**The one rule that shapes this layout comes from ADR-0001: a refusal is a correct
result, not an error.** So a refusal renders with the same visual weight as an answer —
same slot, same typography, no red, no warning icon, no error state. The only difference
is what fills the third slot: an answer fills it with its citations, a refusal fills it
with why refusing was right. Nothing in this file colors a refusal, and nothing should:
the refusal path is the part of this system worth demoing, and styling it as a failure
would argue the opposite of the project's claim.

A genuine error — an unset API key, a rate limit, an unreachable provider — is a separate
slot, deliberately distinct from a refusal. Conflating "the docs don't cover this" with
"the generator is broken" is exactly the distinction this UI exists to make visible.

**Gradio 6 note:** `theme` and `css` moved from the `Blocks` constructor to `launch()`
(passing them to `Blocks` is silently ignored with a warning). `build_app()` therefore
cannot carry them; `launch()` passes `THEME` and `CSS` for you. A caller assembling its
own launch should pass them too — the page reads correctly without them, just plainer.
"""

from __future__ import annotations

import gradio as gr

from infrachat.answer.citations import INSUFFICIENT_GROUNDING
from infrachat.config import Config
from infrachat.models import Answer
from infrachat.pipeline import Deps, Retrieval, answer_from, retrieve

#: Hugging Face Spaces only routes to 7860, and binds nothing but 0.0.0.0 — these are
#: deployment constants, not preferences. Override them for local use, not for Spaces.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7860

#: Demo questions, **verified against the Phase 1 index** rather than guessed. The two
#: refusals are not interchangeable: they trip different gates, which is the whole claim
#: of ADR-0001. The World Cup question scores 0.499 and never reaches the LLM (gate 1);
#: sourdough scores 0.652 and clears the floor — Docker has a build tool called *Bake* —
#: so only reading the excerpts reveals the collision (gate 2).
EXAMPLES: list[str] = [
    "What is a Pod?",
    "How does a multi-stage build work?",
    "Who won the 2022 World Cup?",
    "How do I bake sourdough bread?",
]

#: Cosmetic only. Everything below still reads correctly with this stylesheet absent,
#: which matters because `theme`/`css` live on `launch()` in Gradio 6 and a caller may
#: assemble its own. Deliberately contains no color rule that could single out a refusal.
CSS = """
.infrachat-page { max-width: 880px; margin: 0 auto; }
.infrachat-result { padding: 4px 2px; }
.infrachat-footer { opacity: 0.65; font-size: 0.85em; }
"""

THEME = gr.themes.Soft()

#: Source licenses, for the attribution the docs' licenses require in a public demo
#: (SPEC § Ethics & safety). Keyed by the config source name and looked up with `.get`,
#: so an unknown source degrades to label-plus-repo rather than breaking the footer —
#: `source` is an open string, not a closed enum (ADR-0006).
_LICENSES = {"kubernetes": "CC BY 4.0", "docker": "Apache 2.0"}

_PREVIEW_CHARS = 240


# --------------------------------------------------------------------------- rendering
# Pure string formatting. Kept at module level, and out of the event handler, so the
# wiring below stays readable and each piece can be eyeballed on its own.


def _header(cfg: Config) -> str:
    labels = [s.label for s in cfg.sources] or ["configured"]
    joined = labels[0] if len(labels) == 1 else " and ".join([", ".join(labels[:-1]), labels[-1]])
    return (
        f"## InfraChat\n"
        f"Ask the {joined} docs. Every answer carries the citations it came from — "
        f"or InfraChat says it doesn't know."
    )


def _footer(cfg: Config) -> str:
    parts = []
    for s in cfg.sources:
        lic = _LICENSES.get(s.name)
        name = f"[{s.label}]({s.repo})" if s.repo else s.label
        parts.append(f"{name} ({lic})" if lic else name)
    attribution = " · ".join(parts)
    return (
        f"Answers are drawn from the documentation of {attribution}, used under those "
        f"licenses. Retrieval floor {cfg.retrieval.floor:.2f} · top-{cfg.retrieval.k} "
        f"chunks · embedder `{cfg.embedder.model}`."
    )


def _is_floor_refusal(answer: Answer, cfg: Config) -> bool:
    """Which of the two refusals came back.

    This reads the two **published** refusal messages — `cfg.refusal_message()` (F8) and
    `INSUFFICIENT_GROUNDING` (F9) — to label the outcome. It re-derives nothing: the
    decision was already made in the pipeline, and this only names it for the reader.
    """
    return answer.text == cfg.refusal_message()


def _verdict(answer: Answer, cfg: Config) -> str:
    """The outcome label. Parallel phrasing for all three outcomes, by design."""
    if answer.grounded:
        n = len(answer.citations)
        return f"**Answer** · grounded in {n} cited source{'' if n == 1 else 's'}"
    if _is_floor_refusal(answer, cfg):
        return "**Refusal** · nothing retrieved cleared the grounding floor · gate 1 (F8)"
    if answer.text == INSUFFICIENT_GROUNDING:
        return "**Refusal** · the excerpts did not answer the question · gate 2 (F9)"
    return "**Refusal**"


def _provenance(answer: Answer) -> str:
    """The third slot: citations for an answer, the reasoning for a refusal.

    Both get a bold heading and the same weight. An answer that reached this point
    without a citation is impossible by construction (`Answer.__post_init__`), so there
    is no uncited-answer case to render — that is F9's guarantee, not this function's.
    """
    if not answer.grounded:
        return (
            "**Why this is a correct result**\n\n"
            "InfraChat answers only from the indexed documentation. When the retrieved "
            "excerpts don't support an answer it declines instead of writing a plausible "
            "one — on infrastructure questions a confident wrong answer costs more than "
            "*I don't know* (ADR-0001: refuse over fabricate). Open **Retrieval detail** "
            "below to see exactly what it looked at."
        )

    lines = ["**Sources**", ""]
    for c in answer.citations:
        lines.append(f"- `[{c.tag}]` — {c.source_doc} · {c.source_location}")
    return "\n".join(lines)


def _evidence(r: Retrieval) -> str:
    """What the gate saw — the same view as `ask --retrieval-only`.

    Lists everything retrieval returned, not just what survived the gate: on a refusal
    `decision.hits` is empty on purpose, and the near-misses are the interesting part.
    """
    lines = [
        f"**Grounding gate (F8)** · {r.decision}",
        "",
        f"**Query sent to the retriever** · `{r.query}`",
        "",
    ]
    if not r.hits:
        lines.append("_Retrieval returned no chunks at all._")
        return "\n".join(lines)

    for i, hit in enumerate(r.hits, 1):
        c = hit.chunk
        lines += [
            f"**{i}. {hit.score:.3f}** · `[{c.tag}]` · {c.source_doc} · {c.source_location}",
            "",
            # A fenced block, and the preview collapsed to a single line first: chunk text
            # is raw doc source — Hugo shortcodes, HTML comments, underscores — and in
            # prose a markdown renderer would italicize some of it and swallow the rest.
            # One line can never contain a closing fence, so this renders verbatim with
            # no escaping to get wrong.
            "```text",
            _preview(c.text),
            "```",
            "",
        ]
    return "\n".join(lines)


def _preview(text: str) -> str:
    """Chunk text as one line, trimmed — with the ellipsis only when it really was cut."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _PREVIEW_CHARS else flat[:_PREVIEW_CHARS].rstrip() + " …"


def _trouble(exc: Exception) -> str:
    """A real failure — kept visually separate from a refusal, which is not one."""
    return (
        "**The generator could not be reached, so there is no answer to show.**\n\n"
        "This is a configuration or network failure, *not* a refusal — retrieval and the "
        "grounding gate both ran, and **Retrieval detail** below shows what they found.\n\n"
        f"```\n{exc}\n```"
    )


# ----------------------------------------------------------------------- the handler


def _hide():
    """A fresh `visible=False` update per slot — never a shared dict across requests."""
    return gr.update(visible=False)


def answer_slots(question: str, cfg: Config, deps: Deps):
    """One question → the five slots: verdict, body, provenance, trouble, evidence.

    A generator, so the previous result clears while this one is in flight instead of
    sitting there looking like the answer to the new question.
    """
    question = (question or "").strip()
    if not question:
        yield _hide(), _hide(), _hide(), _hide(), gr.update()
        return

    yield (gr.update(value="_Searching the index…_", visible=True),
           _hide(), _hide(), _hide(), gr.update())

    # Retrieval runs once. The evidence panel needs the Retrieval, and `answer_from`
    # takes that same object rather than re-running it — so this file still never reads
    # the gate decision or decides whether to call the LLM. Both gates stay inside
    # pipeline.py, where a rendering bug cannot route around them.
    try:
        r = retrieve(question, cfg, deps)
    except Exception as exc:            # a missing index or a broken embedder
        yield _hide(), _hide(), _hide(), gr.update(value=_trouble(exc), visible=True), gr.update()
        return

    evidence = gr.update(value=_evidence(r), visible=True)

    try:
        answer = answer_from(r, cfg, deps)
    except Exception as exc:
        # An unset API key, a rate limit, an unconfigured `llm:` block. Gate 1 has
        # already spoken by now, so the evidence panel is still worth showing.
        yield _hide(), _hide(), _hide(), gr.update(value=_trouble(exc), visible=True), evidence
        return

    yield (gr.update(value=_verdict(answer, cfg), visible=True),
           gr.update(value=answer.text, visible=True),
           gr.update(value=_provenance(answer), visible=True),
           _hide(),
           evidence)


# ------------------------------------------------------------------------------ the app


def build_app(cfg: Config, deps: Deps) -> gr.Blocks:
    """The Gradio page. Caller owns `deps`, exactly as `cli.py` builds them for `ask`.

    Styling lives on `launch()` in Gradio 6 — use `launch()` below, or pass `THEME` and
    `CSS` yourself.
    """

    def ask(question: str):
        yield from answer_slots(question, cfg, deps)

    with gr.Blocks(title="InfraChat", analytics_enabled=False) as app:
        with gr.Column(elem_classes="infrachat-page"):
            gr.Markdown(_header(cfg))

            question = gr.Textbox(
                label="Question",
                placeholder="e.g. What does imagePullPolicy do?",
                submit_btn=True,
                autofocus=True,
                lines=1,
            )

            gr.Markdown("Two of these are in the docs and two are not — watch what happens:")
            with gr.Row():
                example_buttons = [gr.Button(q, size="sm") for q in EXAMPLES]

            # The result card. Every slot starts hidden; an answer and a refusal fill the
            # same two — verdict and body — with the same styling. Only the third slot
            # differs: citations for an answer, the reasoning for a refusal. `trouble` is
            # the one slot that means something went wrong, and a refusal never uses it.
            with gr.Group(elem_classes="infrachat-result"):
                verdict = gr.Markdown(visible=False, padding=True)
                body = gr.Markdown(visible=False, line_breaks=True, padding=True)
                provenance = gr.Markdown(visible=False, padding=True)
                trouble = gr.Markdown(visible=False, padding=True)

            with gr.Accordion("Retrieval detail — what the gate saw", open=False):
                evidence = gr.Markdown(
                    "_Ask something to see the retrieved chunks and their scores._"
                )

            gr.Markdown(_footer(cfg), elem_classes="infrachat-footer")

        slots = [verdict, body, provenance, trouble, evidence]
        question.submit(ask, inputs=question, outputs=slots)

        # An example button fills the box, then runs the same handler — so a click is
        # indistinguishable from typing the question by hand.
        for btn, example in zip(example_buttons, EXAMPLES):
            btn.click(lambda q=example: q, outputs=question).then(
                ask, inputs=question, outputs=slots
            )

    return app


def launch(cfg: Config, deps: Deps, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the page and block. `port` defaults to 7860 — the only port Spaces routes."""
    build_app(cfg, deps).launch(
        server_name=host,
        server_port=port,
        theme=THEME,       # Gradio 6: theme and css belong to launch(), not Blocks
        css=CSS,
        show_error=True,
        quiet=False,
    )
