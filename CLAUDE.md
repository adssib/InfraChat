# CLAUDE.md — InfraChat

Guidance for Claude Code in this repo. For the documentation map, read `docs/README.md`.

## What this project is

A retrieval-augmented QA system over the **Kubernetes** and **Docker** docs. It answers from the
docs with citations, or **refuses**. It is built as a **baseline plus one retrieval component at a
time**, with every addition measured against a fixed eval set.

It is a **student portfolio project**. A working, deployed demo matters more than coverage or
polish — but the reasoning must hold up to a senior reviewer.

- Spec: `docs/SPEC.md` · Architecture + diagrams: `docs/ARCHITECTURE.md` · Decisions: `docs/decisions/`

## Working agreement (IMPORTANT — overrides default behavior)

**Never one-shot large amounts of work.** Big single passes overflow both of us and make mistakes
harder to spot and harder to unwind.

- **One step per turn.** A step is *one module*, or *one item from the build order* — not a
  feature, not a layer, not "the ingestion path."
- **Never write a file and its consumers in the same pass.** Write the module, show it, stop.
- **Stop and show after each step.** Print what changed and what it produces. Wait for a response
  before continuing.
- **If a step turns out bigger than expected, split it and say so** — don't push through.
- **Run it after every step.** No test suite means running the thing *is* the verification. A step
  isn't done because the file exists; it's done when its output has been seen.
- Ask before adding a dependency, changing a contract in `docs/SPEC.md`, or reaching for a
  component from a later phase.

## The invariants (breaking these breaks the project's claim)

1. **The two gates never move.** The retrieval floor (F8) and the citation check (F9) are Phase 1
   code that every later phase runs unchanged. Components change *what reaches* the gate — never
   the gate itself. See `docs/decisions/0001-refuse-over-fabricate.md`.
2. **Every optional component is a config-toggled null object.** Identity rewriter, dense-only
   retriever, pass-through reranker. Later phases swap an implementation; **the pipeline is never
   rewired.** `pipeline.py` should stay ~30 lines forever.
3. **Held fixed across all phases:** the question set, the corpus commit, `chunk.*`, and the
   embedder. Changing any of them invalidates comparison with earlier runs.
4. **No answer renders without a citation.** An uncited answer is a refusal, not an answer.

## Stack (verified by spike, not assumed)

| Piece | Choice | Note |
|---|---|---|
| Embeddings | `fastembed` + `BAAI/bge-small-en-v1.5` (384-dim) | **no torch** — ONNX only. Use `query_embed` / `passage_embed`; the model is asymmetric |
| Reranker (P2) | `fastembed` `TextCrossEncoder` | `Xenova/ms-marco-MiniLM-L-6-v2` |
| Store | **one SQLite file** — `sqlite-vec` (vectors) + FTS5 `bm25()` (P3) + relational chunks/manifest | pre-1.0; the `store:` seam is the escape hatch |
| LLM | Groq, OpenAI-compatible client | key from `INFRACHAT_LLM_API_KEY`, env var only |
| UI / CLI / config | Gradio · stdlib `argparse` · pydantic v2 | Gradio on port 7860 for Spaces |

**`retrieval.floor` starts at ~0.55, not 0.35.** Measured: with bge-small, 0.35 refuses nothing —
"how do I bake sourdough bread?" scores 0.409 against these docs. Re-tune on the real corpus.

## Tests

**No test suite.** Three small files only, on pure functions where failure is *silent*:
corpus filter matching, chunker overlap windows, citation tag parsing. No LLM mocking, no
integration tests, no coverage target. The **eval harness is the real quality gate**, and
`ingest --dry-run` / `ask --retrieval-only` are the debugging surface.

## Commands

| Task | Command |
|---|---|
| Ingest | `python -m infrachat ingest -c config.yaml` |
| Inspect chunking (no writes) | `python -m infrachat ingest --dry-run -c config.yaml` |
| Ask | `python -m infrachat ask -c config.yaml "<question>"` |
| Inspect retrieval (no LLM) | `python -m infrachat ask --retrieval-only -c config.yaml "<question>"` |
| Eval | `python -m infrachat eval -c config.yaml` |
| Demo UI | `python -m infrachat serve -c config.yaml` |

## Conventions

- Python 3.12, flat `infrachat/` package. Type hints on function signatures.
- Every module maps to a component in `docs/diagrams/` — **keep the names identical**.
- Secrets are excluded by pattern **before** embedding. Once text is in the index it is retrievable.
- `data/` and `corpus/` are gitignored. `eval/runs/*.jsonl` **is** committed — the results are the point.

## Docs discipline

- **`docs/SPEC.md` is the contract.** If code and SPEC disagree, one is a bug — say which, don't
  silently drift.
- **Every non-trivial decision gets an ADR** — context → options → tradeoff → consequences.
  When a decision changes, write a *new* ADR and mark the old one **Superseded**; never rewrite it.
- **Diagrams live in `docs/diagrams/*.puml`**, rendered to `docs/images/` — three of them:
  `system` (what exists), `ingest-sequence` and `query-sequence` (in what order). Change one,
  re-render, commit both. Later phases appear as optional groups in the sequences, **not** as
  separate diagrams — that duplication is what the old per-phase set got wrong.

## Commit attribution

- One logical change per commit — this falls out of the one-step-per-turn rule above.
- Code Claude writes carries a co-author trailer:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## Ethics & safety

- The LLM key is read from an environment variable only — never in config, never committed.
- The Kubernetes and Docker docs are openly licensed; attribute the source in the public demo.
- **The refusal path is a feature, not a limitation.** On infrastructure questions a confident
  wrong answer is worse than an honest "not in the docs."
