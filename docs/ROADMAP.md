# InfraChat — Roadmap

> The build order. **Each phase is an independently demoable, working system** — the project is
> always in a runnable state, never a big-bang integration at the end.
>
> The organizing idea: **build a baseline, then add one retrieval component at a time, and measure
> the delta against the baseline at every step.** Every phase (from Phase 2 on) is an experiment:
> *did this component earn its place?* The answers — with numbers — become the final write-up.

## Build order

| # | Phase | Delivers | Measure |
|---|---|---|---|
| **1** | **Baseline RAG** — all systems wired | ingest → filter → chunk → **chunk store** → embed → vector store; dense retrieve → grounding gate (floor → refuse) → LLM answer with citations; **eval harness** | **Eval run #1 → baseline numbers** |
| **2** | **+ Reranker** | insert a cross-encoder reranker between retrieve and ground (retrieve top-20 → rerank → keep top-5) | Eval run #2 vs. baseline → *did reranking help?* |
| **3** | **+ Hybrid search** | add a BM25 keyword index; fuse dense + keyword (reciprocal rank fusion) before reranking | Eval run #3 vs. Phase 2 → *did hybrid help, esp. on exact-term queries?* |
| **4** | **+ Query rewriter** | prepend a small/cheap LLM that rewrites/expands the query before retrieval | Eval run #4 vs. Phase 3 → *does rewriting earn its latency?* |
| **5** | **Deep-dive + deploy + write-up** | consolidate all runs into one comparison table; deploy to HF Spaces / home-lab; **optional Postgres + pgvector migration** ([ADR-0004](decisions/0004-sqlite-chunk-store.md)); write the blog/report | The story: baseline → +reranker → +hybrid → +rewriter |

Every phase appears in the same two [sequence diagrams](diagrams/) — later-phase components are
drawn as optional groups, so one picture shows the whole progression. Walkthrough:
[ARCHITECTURE.md § How the system grows](ARCHITECTURE.md#how-the-system-grows).

Phase 1 is the whole pipeline at its simplest — everything after asks *"does adding X beat this
baseline?"* The eval harness (built in Phase 1) is the spine of the entire project.

## The measurement loop (why this project is worth talking about)

Each component phase follows the same loop:

1. **Baseline is fixed** (Phase 1's eval numbers on the fixed question set).
2. **Add exactly one component** via its seam (reranker / hybrid / rewriter), config-toggled.
3. **Re-run the same eval** → get the delta.
4. **Record it** — retrieval hit-rate, grounding correctness, refusal correctness, and (for
   rewriter) added latency/cost.
5. **Write a short section** on what that component bought — including honest negatives.

> This is what turns "I built a RAG system" into a real conversation: *"reranking gave me +X% on
> retrieval hit-rate, hybrid helped most on exact-term queries like flag names and error codes,
> and the query rewriter added latency for marginal gain — so I'd drop it in production."* A
> measured negative result (a component that didn't help) is a **strong** thing to report, not a failure.

## Definition of done (CV-worthy)

- [ ] **Baseline** works: ask "what is a Pod?" / "how does a multi-stage build work?"; get answers
      **with citations** naming the doc set + file/section.
- [ ] **Refusal** works: ask something in neither doc set (e.g. "how do I configure an AWS Lambda?");
      it refuses instead of hallucinating — demoable live, the most compelling moment.
- [ ] **Source attribution** works: a Kubernetes question cites Kubernetes docs, a Docker question
      cites Docker docs.
- [ ] **Eval harness** prints comparable scores per config (baseline, +reranker, +hybrid, +rewriter)
      over one fixed question set.
- [ ] **Each component measured**: a comparison table showing the delta each addition made.
- [ ] **LLM calling** works through the `LLMClient` seam with a cheap/free provider (or local model),
      key from an env var (never committed).
- [ ] **Deployed**: live on Hugging Face Spaces (public URL) or self-hosted on the home-lab.
- [ ] **Write-up**: a blog/report walking through the architecture and what each component bought,
      with numbers and honest conclusions.
- [x] Docs scaffolding: [SPEC.md](SPEC.md), [ARCHITECTURE.md](ARCHITECTURE.md), [EVAL.md](EVAL.md),
      the per-phase PlantUML diagrams, and the first ADRs (starting with
      [refuse over fabricate](decisions/0001-refuse-over-fabricate.md)).
- [ ] An ADR per phase decision that actually gets made, with the numbers that forced it.
- [ ] README leads with the refusal case and a cited answer — the project's POV.

## Notes on sequencing

- **Build the eval harness in Phase 1**, even minimally. Without it, "measure before and after" is
  just a vibe. The fixed question set (k8s-answerable + docker-answerable + should-refuse) makes
  every later delta real. **This is the single most important early decision.**
- **Phase 1 controls cost.** Local CPU embeddings + a **subfolder** of each doc set keep first runs
  free and fast. Do not embed both entire repos on day one — prove it on a subset, then widen.
- **Every component is config-toggled and defaults to off** (null-object). Turning one on is the
  experiment; the same code path runs baseline and enhanced, so comparisons are clean.
- **Phase 3 (hybrid) is where BM25 shines on exact-term queries** — flag names, error codes,
  API fields — the queries dense embeddings often miss. Design a few such questions into the eval set.
- **Fetching the docs live is a later extension**, outside this roadmap. It earns a phase only once
  Phases 1–5 hit "done."
- **Storage stays local through Phase 4.** The stores are files behind one Docker volume so no
  network hop lands inside the p95 numbers Phase 4 is judged on. Postgres/pgvector is a Phase 5
  deployment variant, taken after the measurements are locked.

## Current status

**Phases 1 and 2 are built and committed.** All commands run end to end: `ingest`, `ask`
(and `--retrieval-only`), `eval` (and `--retrieval-only`, `--resume`), `serve`.
`scripts/compare_runs.py` produces every comparison below.

### The fixed set — 87 questions

33 k8s-answerable · 33 docker-answerable · 21 should-refuse. 20 of the 21 refusals are
near-misses built to score *above* the retrieval floor, so they test the citation gate.
Design, discards and spares: `eval/README.md`.

### Phase 1 — baseline (`eval/runs/baseline.jsonl`, floor 0.65)

| metric | value |
|---|---|
| hit-rate@5 · MRR | 0.969 · **0.795** |
| citation validity | **1.000** — no invented citations in 62 answers |
| source accuracy | 0.984 |
| refusal recall · precision | **0.952** · 0.833 |
| false-refusal rate | 0.062 |
| refusals by gate | citation 22 · floor 2 |
| p50 latency | 9.0s (gpt-oss-20b is a reasoning model) |

### Phase 2 — + cross-encoder reranker (`eval/runs/+reranker.jsonl`)

**Retrieval, all 87 questions — final:**

| MRR by slice | n | baseline | +reranker | delta |
|---|---|---|---|---|
| **all answerable** | 66 | 0.788 | **0.867** | **+0.080** |
| cross-source | 4 | 0.375 | 0.875 | **+0.500** |
| docker-answerable | 33 | 0.813 | 0.934 | +0.121 |
| exact-term | 35 | 0.833 | 0.919 | +0.086 |
| paraphrase | 18 | 0.667 | 0.727 | +0.060 |
| k8s-answerable | 33 | 0.763 | 0.801 | +0.038 |

hit-rate@5 0.970 → 0.985. MRR moves five times more than hit-rate — the predicted shape,
since a cross-encoder reorders what retrieval found rather than finding more. Retrieval
latency 47ms → 960ms.

**Generative — final, paired on 86 of 87 questions** (one baseline question exhausted
`max_tokens` while reasoning and is excluded from both arms):

| metric | baseline | +reranker | delta |
|---|---|---|---|
| hit@5 | 0.969 | 0.985 | +0.015 |
| MRR | 0.795 | **0.877** | **+0.082** |
| citation validity | 1.000 | 1.000 | 0 |
| source accuracy | 0.984 | 0.984 | 0 |
| false-refusal rate | 0.062 | 0.046 | −0.015 |
| refusal precision | 0.833 | 0.857 | +0.024 |
| **refusal recall** | **0.952** | **0.857** | **−0.095** |

Verdicts changed on 7 questions: 3 answerable questions newly answered, 2 newly refused,
and **2 should-refuse questions newly answered — both fabrications**:

- `refuse-docker-named-volume` — claims the Dockerfile `VOLUME` instruction "creates a named
  volume". It creates an anonymous one. The reranker promoted `storage/volumes.md` to #1.
- `refuse-etcd-backup-restore` — describes who may access etcd, not how to back it up,
  citing `security/api-server-bypass-risks`: a chunk absent from the baseline's top 3 that
  the reranker put at #1, and exactly the one cited.

**The mechanism:** a cross-encoder finds the most plausible chunk for a question. For an
unanswerable near-miss, that is the most plausible *wrong* chunk. Reranking improves
answerable retrieval and makes near-miss refusals harder, for the same reason. Both escapes
passed the citation gate with **valid** citations — ADR-0007's provenance-vs-entailment
limit, now triggered more often. n=2 of 21 on a provider where temperature 0 is not
deterministic, so this is direction rather than precision; but in both cases the answer is
built from precisely the chunk the reranker newly promoted.

Net on correctness: +1 correct answer, +2 fabrications. By ADR-0001's own ordering —
a confident wrong answer is worse than a refusal — that is not a clean win.

Latency is **not** comparable between these runs: the +reranker run was completed across
six hours by `--resume` under different provider load (p50 3.3s vs 9.3s).

**Verdict: the reranker is a large retrieval win with a measured cost to refusal recall.**
It stays enabled, but the cost is what forces the entailment gate that ADR-0007 recorded
as unscheduled: the citation gate is now provably the weak point, and reranking leans on
it harder. See ADR-0008 for why the reranker decides *order* but not *score*.

**Its other measured cost:** because the gate reads dense cosine, the reranker can only
make gate 1 stricter. `dkr-shrink-image` ranks better (RR 0.5 → 1.0) but its promoted
chunk scores 0.639 against the 0.65 floor — predicted in ADR-0008 before the run.

### Phase 3 — + hybrid search (BM25 + RRF)

**Retrieval, all 87 questions — final** (ADR-0009):

| arm | MRR | exact-term | paraphrase | cross-source | hit@5 | added latency |
|---|---|---|---|---|---|---|
| dense (baseline) | 0.788 | 0.833 | 0.667 | 0.375 | 0.970 | — |
| **+hybrid** | **0.845** | **0.914** | 0.699 | 0.425 | 0.955 | **+6 ms** |
| +reranker | 0.867 | 0.919 | 0.727 | 0.875 | 0.985 | +821 ms |
| +reranker +hybrid | 0.862 | 0.917 | 0.710 | 0.833 | 0.970 | +827 ms |

**Verdict: hybrid is a substitute for the reranker, not an addition to it.** On its own it
buys 71% of the reranker's MRR gain at 0.8% of its latency — and the exact-term win BM25
was built for is real (0.833 → 0.914). Stacked on the reranker it is redundant: 1 question
better, 5 worse, because RRF displaces dense candidates the cross-encoder would have
promoted. The Phase 1 baseline predicted there was little exact-term room left; it was
right, and the negative is recorded rather than tuned away.

**Generative (hybrid only, no reranker): pending** — running through the rolling token
window. The question it answers: does hybrid avoid the refusal-recall cost the reranker
showed? If so, hybrid-only is the better default on both axes.

### What Phases 1-3 tell us about Phase 4

- **Phase 4 (query rewriter) is aimed at paraphrase, now 0.727** — the lowest slice left.
  It must earn that against the latency of an extra LLM call on every query.
- **Every stage so far reorders without rescaling** (ADR-0008, ADR-0009), so the gate
  still reads a dense cosine and `floor` needs no re-derivation. Phase 4 changes the
  *query*, which changes every cosine — re-run the floor rule after it.

### Open

- ⏳ **Entailment gate** — forced by the Phase 2 result above; see ADR-0007.
- ⏳ Deploy to Hugging Face Spaces (image builds and runs locally; nothing has run there).
- ⏳ Minor chunk-content items: `_index` in citation tags (41 docs), HTML comments and
  link URLs left in chunk text. Each changes chunk content and so invalidates every run.
