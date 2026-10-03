# ADR-0012: Streamed answers are drafts until the citation check passes

- **Status:** Accepted
- **Date:** 2026-10-03
- **Phase:** 5 (the demo UI and API, docs/DEMO-PLAN.md)
- **Amends:** invariant 4 in CLAUDE.md ("no answer renders without a citation")

## Context

The web UI streams the answer token by token, the way ChatGPT and Claude do. The citation
check (gate 2, ADR-0001, ADR-0007) can only run once the whole completion exists: it reads
the finished text for tags the model was actually shown. So while tokens arrive, the reader
sees text that gate 2 hasn't judged yet. Read literally, that breaks invariant 4.

Two measurements bound how much this matters:

- **The draft is on screen briefly.** M3 (docs/DEMO-PLAN.md): Groq streams gpt-oss-20b's
  answer in about 0.2 s, after about 1.2 s of reasoning. The live API test on 2026-10-03:
  first answer token at 2.61 s, verdict at 2.67 s.
- **Retraction is rare.** In the shipped `+hybrid` eval run, all 19 gate-2 refusals were the
  model writing `NOT_IN_DOCS`. That is a refusal, not an answer; the UI never shows it as a
  draft. An actual retraction needs the model to write an answer and cite nothing it was
  shown, which happened 0 times in that run.

## Options

1. **Hold, then reveal.** Stream the pipeline steps and the reasoning; buffer the answer and
   show it only after gate 2 passes. Keeps invariant 4 word for word. Costs the streaming
   feel for the one part of the response people read.
2. **Stream as a draft (chosen).** Tokens render dimmed, with raw citation tags, labelled
   "Unverified until the citation check passes". Gate 2 then either turns them into the
   answer (solid text, numbered sources) or withdraws them: the draft is struck through and
   replaced by the refusal card.
3. **Stream as the answer.** Render tokens as if final and swap in a refusal if gate 2 fails.
   Rejected: for that moment an ungrounded answer looks exactly like a grounded one, which is
   the failure the project exists to prevent (ADR-0001).

## Decision

Option 2. The distinction invariant 4 protects is **verified versus not**, and the draft
keeps it visible: different weight, different label, raw tags instead of sources. Nothing
the UI presents as an answer has skipped the gate.

Invariant 4 becomes: **nothing is presented as a verified answer without a citation.** An
uncited answer is still a refusal, not an answer.

## Consequences

- The gates are unchanged. `pipeline.py`, `gate.py` and `citations.py` decide exactly as
  before; the UI reads their verdicts from the event stream (`infrachat/trace.py`) and can
  report a refusal but never cause or prevent one.
- The eval, `ask` and `ask --trace` are unaffected: they print the verdict, not a draft.
- A withdrawn draft is shown, struck through, above the refusal. That makes gate 2 visible
  when it fires, rather than silently replacing text.
- If a future model or provider makes retractions common, revisit this: option 1 is a UI
  change only, because the event contract (docs/DEMO-PLAN.md § Events) is the same either way.
