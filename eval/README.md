# The InfraChat question set

`eval/questions.yaml` is the **fixed** evaluation set: 87 questions, asked verbatim, in the
same order, on every run. [docs/EVAL.md](../docs/EVAL.md) explains the *metrics*. This file
explains the *questions* — how they were designed, what was deliberately rejected, and what
the measured limits of this corpus are, so that nobody re-derives any of it.

Every per-question rationale (measured top-1 score, rank of the expected document, what a
failure would mean) lives in that question's `note:` field in `questions.yaml`. This file
holds only what does not fit in a per-question note.

## The set at a glance

| | |
|---|---|
| Questions | 87 — k8s-answerable 33, docker-answerable 33, should-refuse 21 |
| `question_set_sha256` | `46d4023e5c2b` (first 12 hex of `sha256(eval/questions.yaml)`) |
| Baseline run | `eval/runs/baseline.jsonl` — dense-only, no rerank/hybrid/rewrite |
| Index it was measured against | 281 files, 4,908 chunks (kubernetes 3,898 · docker 1,010) |
| Embedder | `BAAI/bge-small-en-v1.5`, chunks 800/100, `retrieve_n` 20, `k` 5, `floor` 0.55 |

**The corpus is a slice, not the whole docs.** `kubernetes` is
`content/en/docs/concepts` only; `docker` is `content/manuals/build` only. Anything outside
those two subtrees — `docker run`, Compose, Swarm, `kubectl` task pages, the RBAC reference —
is *not answerable here even though it is obviously in-domain*, and belongs in should-refuse.
Most of the design decisions below follow from that one fact.

`expect_docs` paths are relative to the **source root** configured in `sources.yaml`
(`workloads/pods/_index.md`, not `content/en/docs/concepts/workloads/pods/_index.md`); they
are matched against `Chunk.source_doc`. Ranks quoted in notes are **document-level**, matching
how `expect_docs` is scored.

## The three classes

| Class | n | What a failure means |
|---|---|---|
| `k8s-answerable` | 33 | retrieval did not find the right Kubernetes page, or the answer cited the wrong doc set |
| `docker-answerable` | 33 | same for Docker; this half is also where cross-source attribution (F10) is stressed |
| `should-refuse` | 21 | the refusal paths did not fire on a question the corpus cannot answer — i.e. it fabricated |

## The tag vocabulary

Tags are not decoration. docs/EVAL.md requires the per-class breakdown ("hybrid may be flat
overall and decisive on exact-term questions"), and the aggregate cannot be decomposed
without them.

| Tag | n | What it is for |
|---|---|---|
| `exact-term` | 35 | a literal token — `CrashLoopBackOff`, `reservedSpace`, `BUILDKIT_INLINE_CACHE=1`, `--mount=type=cache` — that BM25 should win on. **Phase 3.** Without these, hybrid retrieval has nothing to prove. |
| `paraphrase` | 18 | never uses the answering page's vocabulary ("why is my build printing warnings" for a page titled *Checks*). **Phase 4** — where the rewriter must earn its latency. |
| `near-miss` | 20 | a refusal that is *adjacent* to the corpus, not far from it. Every one was chosen to score **above** `floor=0.55`, so the retrieval gate (F8) cannot catch it and only the citation gate (F9) can — which is the behaviour worth testing ([ADR-0001](../docs/decisions/0001-refuse-over-fabricate.md)). A refusal set of easy misses proves nothing. |
| `cross-source` | 4 | the answer sits in the *other* doc set than the question's vocabulary suggests — an F10 trap. `k8s-nodeselector-placement`, `dkr-build-inside-k8s`, `dkr-shrink-image`, `k8s-secret-for-db-password`. |
| `both-source` | 1 | answerable from *either* doc set; `expect_source` is a list and the check is that the citation names whichever set was actually used. Only `dkr-gpu-access` (Docker CDI ÷ Kubernetes device plugins) holds. |
| `easy` | 4 | the sanity case. If these fail, the index or the embedder changed — not the component under test. |
| *(untagged)* | 8 | ordinary questions that exercise no specific hard case. |

Tags overlap: `k8s-nodeselector-placement` is `[exact-term, cross-source]`.

## "Add more cross-source questions" — no; n=4 is a measured ceiling

The obvious reaction to `cross-source 4 / both-source 1` is that the set is under-built. It
is not. **Two authors probed their areas and found nothing more, and this is the record of
that search so the afternoon is not spent twice.**

- **Docker side (bake / cache / BuildKit / CI).** Across **~25 probe questions**, not one
  Kubernetes chunk reached the top 5. That corner of `manuals/build` shares almost no
  vocabulary with `docs/concepts`. An honest cross-source trap could not be manufactured
  there, so none was claimed.
- **Kubernetes side (workloads).** The Docker slice is `manuals/build`, which owns no
  workload controller, no autoscaler and no scheduler. A both-source workload question would
  have to be *invented* rather than found.
- **Kubernetes side (platform surfaces).** Same result, and with a specific correction:
  docs/EVAL.md uses *"how do I limit container memory?"* as its example of a both-source
  question. **Against this corpus it is not one.** Measured as `k8s-container-memory-limit`:
  top-1 0.802, `configuration/manage-resources-containers.md` at all five ranks, **zero
  Docker chunks**, because `docker run --memory` lives in Docker's engine docs and not in the
  build manuals. It is tagged `paraphrase`, `expect_source: kubernetes`, on the evidence.

The rule that falls out: **verify a cross-source or both-source candidate against the index
before trusting it.** Every one that survived did.

## What was discarded, and why

### Rejected refusal candidates — the corpus *does* answer them

These look unanswerable and are not. Labelling any of them `should-refuse` would score a
**false refusal** against a system that behaved correctly.

| Candidate | Measured | Why it is answerable |
|---|---|---|
| *"How do I publish container port 80 on host port 8080 with `docker run`?"* | top-1 **0.819** | `docker:concepts/dockerfile.md` contains `docker run -p 127.0.0.1:8000:8000 test:latest` and the sentence *"This publishes the container's port 8000 to http://localhost:8000 on the Docker host."* That is an answer. |
| *"Which kubectl command shows the logs of a container that already crashed?"* | — | `kubernetes:cluster-administration/logging.md` states you can use `kubectl logs --previous`, and explains `-c` for multi-container pods. |
| *"How do I troubleshoot a pod stuck in ImagePullBackOff?"* | — | ImagePullBackOff is described in `containers/images.md` and `deployment.md` (4 chunks). Partially answerable, so not a clean refusal. |

The first one is the important one: `docker run` is outside the Docker slice, so it *feels*
like a guaranteed refusal. It isn't.

### Rejected answerable candidates — no supporting document in the baseline top 5

Every answerable question must have a document that answers it inside the top 5 at baseline;
otherwise it measures nothing but noise.

| Candidate | Measured | Verdict |
|---|---|---|
| *"Why does deleting a file in a later step not make my image any smaller?"* | top-1 is **Kubernetes** `scheduling-eviction/node-pressure-eviction.md` 0.707; rank 2 `architecture/garbage-collection.md` | A tempting paraphrase + cross-source trap with no retrievable answer. |
| *"My image works fine on my laptop but crashes on the server with an exec format error"* | top-1 `ci/github-actions/multi-platform.md` **0.670**; `building/multi-platform.md` never appears | "exec format error" occurs nowhere in the corpus; also a near-duplicate of `dkr-multi-platform`. |
| *"Why should I avoid running my container process as root?"* | all five hits Kubernetes (`workloads/pods/user-namespaces.md` **0.812**, …) | The slice's own guidance (`best-practices.md` § USER) is not retrieved at all, and the question is ambiguous about which doc set owns it. |

### Rejected *phrasings* of a question that was kept

`k8s-networkpolicy-default-allow` survives as *"By default, can any pod in the cluster send
traffic to any other pod?"* (top-1 0.788, `network-policies.md` at ranks 1 and 2). Two other
wordings of the same question were discarded rather than recorded as wins:

- *"how do I make sure only the frontend pods can reach the backend pods?"* → `service.md`
  and `replicaset.md`; `network-policies.md` not in the top 5 at all ("frontend"/"backend"
  are Service examples).
- *"how do I restrict which pods are allowed to connect to my database pod?"* → five
  `security/` checklist chunks.

## Verified spares

Measured against the same index, not merged. Use these first if the set is ever extended —
the baseline does not have to be re-derived for them.

| Question | Class | Measured | Why it is held back |
|---|---|---|---|
| *"Why does the builder need my whole project folder?"* | docker-answerable, `paraphrase` | `concepts/context.md` at **rank 2**; top-1 `metadata/attestations/slsa-provenance.md` **0.733** | Usable as-is. Left out only to avoid a third question on `concepts/context.md`. |
| *"Why does my build take a long time sending files before it starts running anything?"* | docker-answerable, `paraphrase` | `concepts/context.md` **absent**; `cache/optimize.md` (which holds the *"Exclude with .dockerignore"* section) at **rank 2**; top-1 `building/best-practices.md` **0.693** | Harder than the one above — a genuine rewriter case, but the expected doc would have to be `cache/optimize.md`. |

The eight rejected candidates in the previous section are also measured, and are recorded
there precisely so they are **not** treated as spares.

## Changing the set

**Adding, removing or rewording a question invalidates comparison with every earlier run**
(docs/EVAL.md § *What makes two runs comparable*: the question set is one of the four things
held fixed). So:

1. Changes land at a **phase boundary only**, never mid-phase.
2. A change is followed by a **baseline re-run**. A table row measured against a different
   question set is not comparable to the rows above it, whatever the numbers say.
3. Every run records `question_set_sha256` in its JSONL header
   (`infrachat/evaluate.py`). The current set is **`46d4023e5c2b`**; `eval/runs/baseline.jsonl`
   carries that value. If two runs disagree on it, they are not comparable — stop and say so.
4. `id` is the JSONL row key and is **never renamed**, even if the wording changes.
5. A new question is not finished until it has been run through
   `./.venv/bin/python -m infrachat ask --retrieval-only "<question>"` against the index,
   every `expect_docs` path has been confirmed against `chunks.source_doc`, and its measured
   top-1 score and expected-doc rank are written into its `note:`. Unmeasured questions are
   how a set starts flattering the system.

For a refusal specifically, add one more step: a literal `instr(lower(text), …)` scan of the
chunks table for the terms an answer would have to contain, so the note can state what the
corpus *does* say. That scan is what caught the three false refusals above. The 11 refusals
added most recently were all verified this way and all clear the floor — min **0.709**,
median **0.779**, max **0.834**.
