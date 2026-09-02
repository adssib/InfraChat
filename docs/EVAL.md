# InfraChat — Evaluation

> **How every claim in this project becomes a number.** The eval harness is built in Phase 1,
> before any optional component exists, because without it *"did the reranker help?"* is a vibe.
> See [ADR-0003](decisions/0003-eval-harness-is-phase-1.md) and [ROADMAP.md](ROADMAP.md).

## What makes two runs comparable

A delta only means something if exactly one thing changed. Every run pins all four:

| Held fixed | Why |
|---|---|
| **The question set** | Same questions, same order, every phase. Adding questions invalidates comparison with earlier runs — add them at a phase boundary and re-run the baseline. |
| **The corpus commit** | The docs move upstream. A pinned clone means a delta is your component, not Kubernetes shipping a new page ([SPEC § Corpus](SPEC.md#corpus--what-documents-from-where)). |
| **The chunking config** | `chunk.size` and `chunk.overlap` change what "the right chunk" even is. Set once, hold across all phases. |
| **The embedder** | Similarity scores are not comparable across models — and `floor` is calibrated against them. |
| Changed: **one seam** | `rerank.enabled` / `hybrid.enabled` / `rewrite.enabled` — labelled by `run_label`. |

**The generator LLM is the awkward one.** Hosted models change under you without a version bump.
Pin an explicit model version where the provider offers one, and record the model string in the
run output. If it changed between runs, say so next to the numbers.

## The question set

`eval/questions.yaml` — three classes, deliberately balanced:

| Class | What it proves | Rough share |
|---|---|---|
| **k8s-answerable** | retrieval finds the right Kubernetes page; the answer cites Kubernetes | ~40% |
| **docker-answerable** | same for Docker; **cross-source attribution isn't confused** (F10) | ~40% |
| **should-refuse** | the refusal paths fire on questions the corpus can't answer | ~20% |

Each entry names the chunk(s) that *should* be retrieved, so hit-rate is checkable:

```yaml
- id: k8s-pod-basics
  question: "What is a Pod?"
  class: k8s-answerable
  expect_source: kubernetes
  expect_docs: ["content/en/docs/concepts/workloads/pods/_index.md"]

- id: refuse-lambda
  question: "How do I configure an AWS Lambda function?"
  class: should-refuse
  expect_source: null
  expect_docs: []
```

**Design the hard cases in deliberately**, or the eval flatters the system:

- **Exact-term questions** — `CrashLoopBackOff`, `--mount=type=cache`, `imagePullPolicy`.
  These are where BM25 should beat dense retrieval; without them Phase 3 shows nothing.
- **Paraphrase questions** — *"how do I make my image smaller?"* never says "multi-stage".
  These are where the Phase 4 rewriter should earn its latency.
- **Near-miss refusals** — *"how do I configure an AWS Lambda?"* is easy. *"how does Podman
  rootless networking work?"* is adjacent to the corpus and much harder to refuse correctly.
  A refusal set made only of easy misses proves nothing.
- **Both-source questions** — *"how do I limit container memory?"* is answerable from either
  doc set; check the citation names whichever it actually used.

## Metrics

### Retrieval

| Metric | Definition | Reads |
|---|---|---|
| **hit-rate@k** | share of answerable questions where ≥1 expected doc is in the final top-`k` | did retrieval *find* it? |
| **MRR** | mean reciprocal rank of the first expected doc | did retrieval *rank* it well? — this is what reranking should move |

`hit-rate@k` alone will hide a reranker's value: if the right chunk was already in the top-5 it
stays a hit whether it's ranked 1st or 5th. **Track MRR too, or Phase 2 looks like a no-op.**

### Grounding & refusal

| Metric | Definition |
|---|---|
| **citation validity** | share of answers whose `[source:location]` tags all match a retrieved chunk |
| **source accuracy** | share of answers citing the *correct* doc set (F10) |
| **refusal recall** | share of `should-refuse` questions that were refused — *missing this means it fabricated* |
| **refusal precision** | share of refusals that *should* have been refusals — low means it's over-refusing |
| **false-refusal rate** | share of answerable questions wrongly refused |

**Report refusal precision and recall separately.** A system that refuses everything scores 100%
recall and is useless; the false-refusal rate is what stops a component from "improving" the
numbers by making the gate trigger-happy.

### Cost

| Metric | Why it's here |
|---|---|
| **p50 / p95 query latency** | the rewriter (Phase 4) adds an LLM call to every query |
| **tokens per query** | prompt + completion, both LLM roles |

Quality that costs 2× latency is a tradeoff, not a win. Phase 4 is judged on both columns.

## Where results land

Per-question results are written as **flat JSONL** — `eval/runs/<run_label>.jsonl`, one row per
question, committed to the repo. Deliberately *not* in the database: four runs of ~30 questions
isn't a database's problem, and a committed results file is readable by anyone reviewing the repo
([ADR-0004](decisions/0004-sqlite-chunk-store.md)). Each row carries the question id, class,
retrieved doc ids, whether it was refused, the citations, and latency; each file carries the run's
corpus commit, embedder, generator model, and date in its first line.

## The comparison table

Every phase appends one row. This table *is* the Phase 5 write-up:

| Run | hit-rate@5 | MRR | citation validity | source accuracy | refusal recall | false-refusal | p95 latency | Verdict |
|---|---|---|---|---|---|---|---|---|
| `baseline` (P1) | — | — | — | — | — | — | — | reference |
| `+reranker` (P2) | | | | | | | | |
| `+hybrid` (P3) | | | | | | | | |
| `+rewriter` (P4) | | | | | | | | |

Alongside each row, record: question count, corpus commit, embedder, generator model, and date.

## Reading the results honestly

- **State the question count next to every number.** On a 30-question set, one question is 3.3
  points — most "improvements" smaller than that are noise, not signal.
- **A negative result is a finding, not a failure.** *"The query rewriter added 900ms p95 for
  +1.2 points of hit-rate, so I'd drop it in production"* is a stronger thing to be able to say
  than a table where everything helped. Write it up as a result.
- **Break the numbers down by class.** Hybrid may be flat overall and decisive on exact-term
  questions — the aggregate would hide the single most interesting finding in the project.
- **Watch the gate when a stage rewrites scores.** Reranking and fusion replace `score` with a
  different scale, and `floor` reads `hits[0].score`. If refusal rates jump in Phase 2 or 3, the
  component may not have changed retrieval quality at all — it may just have moved the floor's
  meaning. Check this before reporting any refusal-metric delta (see
  [ARCHITECTURE.md](ARCHITECTURE.md#assumptions--risks-on-the-record)).
