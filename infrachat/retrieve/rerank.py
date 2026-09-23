"""F12 — the reranker seam, with its Phase 1 null object and its Phase 2 implementation.

The pass-through is not a placeholder to be replaced by "the real code" — it is the
baseline arm of the experiment. Phase 1 and Phase 2 run the *same* pipeline; only this
object differs. That is what makes the A/B honest (ADR-0002).

## The score decision (read this before changing anything here)

`Retrieved.score` is the field the grounding gate reads, so **whatever stage last writes
it defines what `retrieval.floor` means** (SPEC § The rest; ARCHITECTURE § Assumptions
names this "the sharpest edge in the whole design"). `floor: 0.65` is not a free constant:
`eval/floor-tuning.md` derives it as `min(answerable top-1) - 1 SD` of one specific
distribution — **bge-small cosine similarity in [0,1]** over this question set.

A cross-encoder does not produce that number. `ms-marco-MiniLM` emits an unbounded
relevance **logit**; measured over the 1740 query/chunk pairs this eval set produces, it
spans -11.43 to +9.57, and its sigmoid is close to bimodal — 46.8% of pairs below 0.1,
25.7% above 0.9, only 27.5% anywhere in between. Three ways to populate `score` were
available:

1. **Write the raw logit.** Fails immediately: the value is not in [0,1] (SPEC pins that
   range), and a floor of 0.65 would land inside the mildly-positive band of a scale
   running to ±11 — it would pass anything the model did not actively dislike. The gate
   would still be the same code, but it would be testing a different quantity.
2. **Write `sigmoid(logit)`.** Back in [0,1] and tempting — but calibration, not range, is
   what `floor` encodes. Measured on the same 87 questions, top-1 `sigmoid(CE)` has sd
   0.2415 against dense cosine's 0.0529, and holding `floor` at 0.65 moves the gate from
   **1/66 answerable questions refused to 8/66**, while gate-1 catches of `should-refuse`
   go from 2/21 to 8/21. Some of that looks like an improvement, which is exactly the
   trap: the Phase 2 eval row would be measuring **reranking plus a re-tuned refusal
   threshold** — two changes, one number, and ADR-0002's whole purpose defeated.
3. **Keep the dense cosine and reorder only.** ← what this does.

**The cross-encoder decides ORDER; the dense retriever still decides SCORE.** Each
`Retrieved` is handed back untouched, carrying the cosine similarity that surfaced it;
only their positions change. The scale reaching the gate is identical in both arms, so
`floor` keeps meaning exactly what it meant in Phase 1 and the eval delta is attributable
to ranking alone. This is also what MRR and hit-rate@k measure (EVAL § Retrieval) — both
read *order*, which is precisely the thing Phase 2 changes.

### The consequence, stated rather than hidden

The gate reads `hits[0].score`. After reranking, `hits[0]` is the chunk the cross-encoder
liked best, whose cosine is **≤** the cosine of the dense top-1 it displaced. So enabling
this component can only make the floor gate *stricter*, never looser: a question can flip
pass → refuse, never refuse → pass. That is a real effect of changing what reaches the
gate (which components are allowed to do) rather than a change to the gate itself (which
they are not) — but it is an effect worth counting, so the Phase 2 eval run should report
`floor_refusals` alongside MRR.

Measured here, it bites exactly once in 87 questions, and instructively:
*"My image is 1.5GB. How do I shrink it?"* improves from rank 2 to rank 1 (RR 0.500 →
1.000) because the cross-encoder promotes `building/best-practices.md#4` over an SLSA
provenance page that dense retrieval put first. The promoted chunk's cosine is 0.639
against the displaced 0.722, so gate top-1 lands at 0.639 and misses a floor of 0.65 by
0.011. **A better answer, refused.** That is the honest cost of this design; the right
response is a floor re-calibration argued in its own ADR, not a score written back here
to make one number look better.

If a later phase wants the cross-encoder's own confidence at the gate, that is a **floor
re-calibration** and a separate experiment: a new ADR, a re-tuned `floor`, and its own
eval row. It is not a tweak to this file.
"""

from __future__ import annotations

from typing import Protocol

from infrachat.config import RerankConfig
from infrachat.models import Retrieved


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]: ...


class PassthroughReranker:
    """Keep the retriever's order, keep the top `top_k`. The Phase 1 baseline.

    Note it still truncates: `retrieve_n` candidates come in, `k` go to the gate. Without
    that, the baseline would send 20 chunks to the LLM and Phase 2's improvement would be
    confounded with sending fewer.
    """

    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]:
        return hits[:top_k]


class CrossEncoderReranker:
    """Phase 2 — re-order the candidates by joint query/chunk relevance, keep `top_k`.

    The dense retriever embeds question and chunk *separately*, which is what makes it
    cheap enough to run over the whole corpus and blunt enough to need this. A
    cross-encoder reads the pair together, so it is far more accurate and far too slow for
    anything but a short candidate list — hence the two-stage shape: recall
    `retrieval.retrieve_n` cheaply, re-order precisely, keep `retrieval.k`.

    Like `FastEmbedEmbedder`, the model is loaded **lazily**: importing this module must
    not download ~90MB, so `--help`, `--dry-run` and a disabled config stay instant and
    offline. An empty candidate list also short-circuits before the load — a question that
    retrieved nothing must not pay for a model it has no use for.

    It does **not** touch `Retrieved.score` — see the module docstring; that decision is
    the load-bearing one here.
    """

    def __init__(self, model_name: str, *, batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            # imported here, not at module level: see the lazy-load note above
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(self.model_name)
        return self._model

    def scored(self, query: str, hits: list[Retrieved]) -> list[tuple[Retrieved, float]]:
        """The ranking with the cross-encoder logits attached, best first.

        Exposed because `rerank()` deliberately throws these numbers away, and a score
        you cannot inspect is a score you cannot debug or calibrate. Nothing in the
        pipeline calls this — it is for the notebook, the ADR, and any future decision to
        re-tune `floor` against this scale.
        """
        if not hits:
            return []
        logits = list(self._load().rerank(query, [h.chunk.text for h in hits],
                                          batch_size=self.batch_size))
        # `sorted` is stable, so chunks the cross-encoder scores identically keep the
        # dense retriever's relative order rather than an arbitrary one.
        return sorted(zip(hits, logits), key=lambda pair: -pair[1])

    def rerank(self, query: str, hits: list[Retrieved], top_k: int) -> list[Retrieved]:
        """Re-order by cross-encoder relevance, then truncate exactly as the baseline does.

        The returned objects are the *same* `Retrieved` instances that came in, with their
        dense scores intact. Only their positions differ.
        """
        if not hits:
            return []
        return [hit for hit, _ in self.scored(query, hits)][:top_k]


def build(cfg: RerankConfig) -> Reranker:
    """Construct the configured reranker — the one place the implementation is named.

    Mirrors `embed.build`. The toggle lives here rather than at the call site so the
    caller assembling `Deps` never grows an `if` per phase (ADR-0002): a disabled block
    and an absent one both yield the null object.
    """
    return CrossEncoderReranker(cfg.model) if cfg.enabled else PassthroughReranker()
