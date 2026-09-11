"""F8 — the grounding gate: refuse when retrieval isn't confident enough.

The first of two independent refusals (ADR-0001). This one is **model-free and cheap**:
it runs before the LLM is called, so a hopeless question costs nothing. The second gate,
the citation check, catches what similarity cannot see — chunks that clear the floor but
do not actually answer the question.

**This code never changes again.** Phases 2-4 alter what *reaches* the gate — reranked
order, fused arms, a rewritten query — but not the gate itself. That invariant is what
makes the phase-to-phase comparisons honest, so treat any edit here as a change to the
experiment, not to a detail.
"""

from __future__ import annotations

from dataclasses import dataclass

from infrachat.models import Retrieved


@dataclass(frozen=True)
class GateDecision:
    """The verdict, plus the evidence behind it.

    `top_score` is reported **even on a refusal** — the eval harness needs to know how
    close a refusal was in order to tune `floor`, and a bare pass/fail would throw away
    the only signal that makes that tunable.
    """

    passed: bool
    hits: list[Retrieved]
    floor: float
    top_score: float | None   # None only when retrieval returned nothing at all

    @property
    def margin(self) -> float | None:
        """Distance from the threshold. Negative means it refused, and by how much."""
        return None if self.top_score is None else self.top_score - self.floor

    def __str__(self) -> str:
        if self.top_score is None:
            return f"refused: retrieval returned no chunks (floor={self.floor:.2f})"
        verb = "passed" if self.passed else "refused"
        return f"{verb}: top-1 {self.top_score:.3f} vs floor {self.floor:.2f} (margin {self.margin:+.3f})"


def check(hits: list[Retrieved], floor: float) -> GateDecision:
    """Pass the hits through, or refuse.

    Only the **top-1** score is tested. Averaging the top-k would let several mediocre
    chunks outvote the absence of a good one, which is exactly the case this gate exists
    to catch: retrieval always returns *something*, and the question is whether the best
    thing it found is good enough.
    """
    if not hits:
        return GateDecision(passed=False, hits=[], floor=floor, top_score=None)

    top = hits[0].score
    passed = top >= floor
    return GateDecision(
        passed=passed,
        hits=hits if passed else [],
        floor=floor,
        top_score=top,
    )
