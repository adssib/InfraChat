# Tuning `retrieval.floor` — what the evidence supports

> **Analysis only. No code or config was changed.** Source: `eval/runs/baseline.jsonl`
> (`run_label: baseline`, 2026-09-11, 87 questions, retrieval-only, no LLM calls).
> Embedder `BAAI/bge-small-en-v1.5`, chunk 800/100, `retrieve_n: 20`, `k: 5`,
> corpus `00ace9ca` (k8s) + `ff96ad17` (docker), 4908 chunks.
> All scores below are `top_score` = `hits[0].score` = exactly what gate 1 tests
> (`infrachat/answer/gate.py::check`).

## TL;DR

| Question | Answer |
|---|---|
| Does any floor cleanly separate answerable from should-refuse? | **No.** The classes overlap over `[0.7014, 0.8337]`, which contains 67 of the 87 questions (77%). |
| Accuracy-maximising floor (gate 1 alone) | **0.73** — 69/87 correct (79.3%), but it buys 6 extra refusals with 4 false refusals, and it does **not** survive cross-validation (see §6). |
| Highest floor with zero false refusals | **0.70** — and the margin to the nearest answerable question is **0.0014**. Unusable as-is. |
| **Recommended floor** | **0.65** — the largest value with zero false refusals *and* a real safety margin (≈1 SD of the answerable distribution). |
| What this is evidence *for* | That the floor cannot be a refusal classifier on this corpus, and that raising it above ~0.70 is a losing trade. |
| What this is **not** evidence for | That 0.65 is optimal, or that any refusal metric may be reported for 0.65 against these same 87 questions (§6). |

Moving 0.55 → 0.65 changes the outcome of **exactly one** of 87 questions. That is the honest
size of this finding, and it is deliberately small.

---

## 1. Score distributions by class

All 87 rows have a non-null `top_score`; `passed_floor` agrees with `top_score >= 0.55` on every
row, so the recorded field and the gate logic are consistent.

| Class | n | min | Q1 | median | Q3 | max | mean | SD |
|---|---|---|---|---|---|---|---|---|
| k8s-answerable | 33 | 0.7014 | 0.7690 | 0.7973 | 0.8295 | 0.8787 | 0.7965 | 0.0434 |
| docker-answerable | 33 | 0.7215 | 0.7732 | 0.8075 | 0.8417 | 0.8688 | 0.8053 | 0.0417 |
| **all answerable** | **66** | **0.7014** | 0.7714 | 0.8022 | 0.8358 | 0.8787 | 0.8009 | 0.0428 |
| **should-refuse** | **21** | 0.4717 | 0.7294 | 0.7648 | 0.7954 | **0.8337** | 0.7472 | 0.0749 |

The two answerable classes are near-identical (medians 0.797 vs 0.808) — **one floor serves both**;
there is no case for a per-source threshold.

The refusal class is not a distribution, it is two distributions: two genuinely out-of-domain
questions far below everything, and nineteen near-misses sitting *inside* the answerable range.
The mean (0.747) is a fiction that describes no question in the set.

## 2. Histogram (bin width 0.025) — `#` answerable, `*` should-refuse

```
0.450-0.475 | A  0                | R  1 *
0.475-0.500 | A  0                | R  0
0.500-0.525 | A  0                | R  0
0.525-0.550 | A  0                | R  0      <- current floor 0.55 sits here
0.550-0.575 | A  0                | R  0
0.575-0.600 | A  0                | R  0
0.600-0.625 | A  0                | R  0
0.625-0.650 | A  0                | R  1 *
0.650-0.675 | A  0                | R  0      <- recommended floor 0.65
0.675-0.700 | A  0                | R  0
0.700-0.725 | A  3 ###            | R  2 **   <- overlap starts (0.7014)
0.725-0.750 | A  6 ######         | R  6 ******
0.750-0.775 | A 10 ##########     | R  3 ***
0.775-0.800 | A 12 ############   | R  4 ****
0.800-0.825 | A 13 #############  | R  3 ***
0.825-0.850 | A 12 ############   | R  1 *    <- overlap ends (0.8337)
0.850-0.875 | A  9 #########      | R  0
0.875-0.900 | A  1 #              | R  0
```

Note the empty band from 0.475 to 0.700: **nothing at all lives between the two easy refusals and
the answerable floor.** That gap is the only region where a threshold is safe, and it is the region
the floor is currently in.

Note also how compressed the whole range is. With bge-small cosine similarity nothing scores below
0.47 — "How do I bake sourdough bread?" against Kubernetes docs still returns 0.65. A floor at 0.35
(CLAUDE.md's rejected value) refuses literally nothing; that part of the original calibration was
right. The provisional 0.55 is *safe*, just nearly inert.

## 3. Floor sweep, 0.40 → 0.90 — gate 1 acting alone

- **refusal recall** = should-refuse questions the floor catches / 21
- **false-refusal rate (FRR)** = answerable questions the floor wrongly refuses / 66
- **precision** = should-refuse refused / all questions refused
- **accuracy** = (refusals caught + answerable passed) / 87

| floor | caught /21 | recall | false-ref /66 | FRR | precision | correct /87 | acc |
|---|---|---|---|---|---|---|---|
| 0.40–0.47 | 0 | 0.0% | 0 | 0.0% | — | 66 | 75.9% |
| 0.48–0.64 | 1 | 4.8% | 0 | 0.0% | 100.0% | 67 | 77.0% |
| **0.55** *(current)* | **1** | **4.8%** | **0** | **0.0%** | **100.0%** | **67** | **77.0%** |
| **0.65–0.70** | **2** | **9.5%** | **0** | **0.0%** | **100.0%** | **68** | **78.2%** |
| 0.71 | 3 | 14.3% | 1 | 1.5% | 75.0% | 68 | 78.2% |
| 0.72 | 3 | 14.3% | 2 | 3.0% | 60.0% | 67 | 77.0% |
| **0.73** *(acc. max)* | **7** | **33.3%** | **4** | **6.1%** | **63.6%** | **69** | **79.3%** |
| 0.74 | 7 | 33.3% | 6 | 9.1% | 53.8% | 67 | 77.0% |
| 0.75 | 10 | 47.6% | 9 | 13.6% | 52.6% | 67 | 77.0% |
| 0.76 | 10 | 47.6% | 13 | 19.7% | 43.5% | 63 | 72.4% |
| 0.77 | 13 | 61.9% | 16 | 24.2% | 44.8% | 63 | 72.4% |
| 0.78 | 14 | 66.7% | 20 | 30.3% | 41.2% | 60 | 69.0% |
| 0.79 | 15 | 71.4% | 25 | 37.9% | 37.5% | 56 | 64.4% |
| 0.80 | 17 | 81.0% | 31 | 47.0% | 35.4% | 52 | 59.8% |
| 0.81 | 17 | 81.0% | 38 | 57.6% | 30.9% | 45 | 51.7% |
| 0.82 | 20 | 95.2% | 43 | 65.2% | 31.7% | 43 | 49.4% |
| 0.83 | 20 | 95.2% | 47 | 71.2% | 29.9% | 39 | 44.8% |
| 0.84 | 21 | 100.0% | 50 | 75.8% | 29.6% | 37 | 42.5% |
| 0.85 | 21 | 100.0% | 56 | 84.8% | 27.3% | 31 | 35.6% |
| 0.86 | 21 | 100.0% | 61 | 92.4% | 25.6% | 26 | 29.9% |
| 0.87 | 21 | 100.0% | 64 | 97.0% | 24.7% | 23 | 26.4% |
| 0.88–0.90 | 21 | 100.0% | 66 | 100.0% | 24.1% | 21 | 24.1% |

*(Rows 0.40–0.64 are collapsed because every 0.01 step in those ranges is identical; the only
transitions are at 0.48 and 0.65. The full 51-row sweep is reproducible from the JSONL with the
definitions above.)*

**Read the bottom of the table as the reductio.** Floor 0.88 achieves 100% refusal recall and is a
system that answers nothing. Refusal recall alone is not a score that can be maximised — this is
`docs/EVAL.md` § "Grounding & refusal" in one column of numbers.

### The two named floors

- **Accuracy-maximising: 0.73** — 69/87 (79.3%). Beats the current 0.55 by **2 questions**. On an
  87-question set one question is 1.15 points, so the entire "improvement" is under two questions of
  noise, and it is paid for with 4 real false refusals (6.1% FRR).
- **Highest zero-false-refusal: 0.70** — catches 2/21, 0 false refusals. But the lowest answerable
  question, `k8s-autoscale-on-traffic` ("paraphrase"), scores **0.7014**. A floor of 0.70 sits
  **0.0014** beneath a real answerable question. That is not a threshold, it is a coincidence.

## 4. Is there clean separation? No. Here is the overlap.

**Overlap region: `[0.7014, 0.8337]`, width 0.1323.** It contains **48 of 66 answerable (73%)** and
**19 of 21 should-refuse (90%)** — 67/87 questions, 77% of the set. No threshold anywhere in that
band can do better than trade one error type for the other.

Only **two** refusals fall below the overlap:

| id | top_score | why it is separable |
|---|---|---|
| `refuse-capital-of-france` | 0.4717 | no lexical or topical contact with the corpus at all |
| `refuse-sourdough-bake` | 0.6475 | the documented Bake collision — still 0.18 below the answerable floor |

And these near-misses sit **above** the lowest answerable questions:

| top should-refuse scores | | lowest answerable scores | |
|---|---|---|---|
| `refuse-gitlab-ci-pipeline` | **0.8337** | `k8s-autoscale-on-traffic` (paraphrase) | **0.7014** |
| `refuse-control-plane-sizing` | 0.8160 | `k8s-anti-affinity-spread` (paraphrase) | 0.7129 |
| `refuse-docker-named-volume` | 0.8134 | `dkr-shrink-image` (paraphrase) | 0.7215 |
| `refuse-terraform-namespace` | 0.8116 | `k8s-init-container-wait` (paraphrase) | 0.7278 |
| `refuse-gitlab-ci` | 0.7976 | `k8s-secret-for-db-password` (paraphrase) | 0.7301 |
| `refuse-nginx-ingress-annotations` | 0.7954 | `dkr-cache-layer-ordering` (paraphrase) | 0.7306 |

Every refusal in the left column outscores every question in the right column. Note what the right
column is made of: **the questions the floor is closest to refusing are almost all `paraphrase`** —
the class `docs/EVAL.md` says the Phase 4 rewriter exists to rescue. A raised floor would refuse
precisely the questions a later phase is meant to improve, and would make Phase 4 look like it fixed
a retrieval problem when it had really only undone a threshold.

The inversion is systematic, not accidental: **`refuse-gitlab-ci-pipeline` (0.8337) outscores 48 of
the 66 questions the system is supposed to answer.** The floor would have to reach 0.84 to catch it,
by which point it has refused 50 of 66 good questions.

**The structural reason:** 20 of the 21 refusal questions carry the `near-miss` tag. They were
*designed* to clear the floor — `refuse-keda-scaledobject` asks about a term the corpus literally
names; `refuse-rbac-role-vs-clusterrole` is unmistakably in-domain and merely outside the
`docs/concepts` slice. Cosine similarity measures topical proximity. These questions are *topically
correct and factually unanswerable*, and that distinction is invisible to a similarity score by
construction. **This is not a tuning failure. It is the boundary of what gate 1 can ever know**, and
it is exactly the case ADR-0001 predicted when it rejected "floor only, no citation check":
*"similarity is not sufficiency."*

## 5. The recommendation: 0.65 — and what the floor is actually for

### The objective is wrong if it is "maximise refusal recall"

Gate 1 is not the refusal system. It is the **first** of two independent gates (ADR-0001), and the
two error types it can make are not symmetric in *recoverability*:

| Gate 1 error | What happens next | Recoverable? |
|---|---|---|
| **False refusal** (answerable question refused) | Pipeline stops. No LLM call, no retrieval shown, user gets "Not found in the Kubernetes or Docker docs." for a question the docs *do* answer. | **Never.** No downstream stage can un-refuse. |
| **Missed refusal** (near-miss clears the floor) | Chunks go to the LLM, which is instructed to emit `NOT_IN_DOCS`, and every claim must carry a `[source:location]` tag matching a retrieved chunk. | **Yes — that is gate 2's entire job.** |

A false refusal is a terminal error at gate 1. A missed refusal is a *handoff* to the gate built for
precisely this case. So the floor should be set to the highest value that is **safely** below the
answerable distribution — not the value that catches the most refusals.

**What the floor is for, stated plainly:** gate 1 is an out-of-distribution trip-wire and a cost
guard, not a classifier. It exists to stop questions with *no contact with the corpus* ("capital of
France", sourdough) before they cost an LLM call, and to keep the system honest when retrieval
genuinely finds nothing. Discriminating "in-domain but unanswerable" is gate 2's work, and no value
of this constant will move that work to gate 1. Gate 1 should carry ~2/21 of the refusals on this
set; **gate 2 must carry the other 19.** If gate 2 cannot, the fix is in the prompt and the citation
matcher, not in this number.

### Why 0.65

A decision rule fixed *before* looking at which value wins: **take the observed answerable minimum
and subtract one standard deviation of the answerable distribution**, then round down to 0.01.

```
0.7014 (min answerable) − 0.0428 (SD answerable) = 0.6586  →  0.65
```

| | 0.55 (current) | **0.65 (recommended)** | 0.70 (zero-FR ceiling) | 0.73 (acc. max) |
|---|---|---|---|---|
| false refusals | 0 | **0** | 0 | 4 (6.1%) |
| refusals caught | 1/21 | **2/21** | 2/21 | 7/21 |
| headroom to nearest answerable | 0.1514 | **0.0514** | 0.0014 | −0.03 (breached) |
| LLM calls skipped | 1/87 (1.1%) | **2/87 (2.3%)** | 2/87 | 11/87 (12.6%) |

0.65 catches both of the genuinely out-of-domain questions — which is all gate 1 is for — keeps
~1.2 SD of headroom beneath the lowest real answerable question, and doubles the (small) cost
saving. 0.70 catches the same two questions with 3.6% of the headroom; there is no reason to take
that risk for zero additional benefit.

**The safety margin is not theoretical.** Cross-validated, the "sit at the observed minimum" policy
produces a **1.9% false-refusal rate on held-out questions** — the zero-FR ceiling is zero-FR only
on the sample it was measured on. The 0.65 policy holds at **0.0%** (§6).

### Sensitivity

The zero-FR ceiling is set by a **single question**. Bootstrap over the 66 answerable scores
(5000 resamples): median min 0.7014, 97.5th percentile **0.7278**. Leave-one-out: drop
`k8s-autoscale-on-traffic` and the ceiling jumps to 0.7129; drop two and it is 0.7215. Any floor
placed against that minimum is fitted to one paraphrase question. 0.65 is insensitive to all of it.

### What should change instead of the floor

- Nothing, if gate 2's refusal recall on the 19 near-misses is acceptable — measure that first, on
  a day with LLM budget.
- If false refusals ever dominate (they do not here — **0 at any floor ≤ 0.70**), ADR-0001 already
  names the fix: a calibrated per-query threshold, not a global constant.
- **The floor must be re-derived whenever the embedder changes** (ADR-0001, `docs/EVAL.md`), and
  also whenever a stage rewrites `score` — the reranker (P2) and fusion (P3) put a *different scale*
  into `hits[0].score`. 0.65 is a statement about bge-small cosine similarity and nothing else.
  `docs/EVAL.md` § "Reading the results honestly" already flags this; it is the most likely way this
  number silently becomes wrong.

---

## 6. ⚠️ The circularity problem — and how it was handled

**These 87 questions are the eval set.** Choosing a threshold to maximise a score on the same
questions the system is then scored against is exactly the error this project exists to avoid. Any
floor selected here is fitted to this sample, and the resulting metrics are optimistically biased.

### The bias is measurable, and it is large

5-fold cross-validation, stratified by class, 200 repetitions. The *procedure* is re-run on each
training split and evaluated on the held-out fold:

| Policy | Held-out accuracy | Held-out FRR |
|---|---|---|
| Pick the accuracy-maximising floor on the training folds | **75.2%** | 5.7% |
| Pick the highest zero-FR floor on the training folds | 77.0% | **1.9%** |
| Fixed 0.55, chosen a priori (no fitting) | 77.1% | **0.0%** |
| Fixed **0.65**, decision-rule value | **78.2%** | **0.0%** |

The accuracy-tuned floor scores **79.5% on its training folds and 75.2% held out — 4.4 points of
pure optimism**, and it generalises *worse than not tuning at all*. This is the circularity
quantified: the 79.3% reported for floor 0.73 in §3 is a number that does not survive contact with
questions it was not fitted to. **Recommending 0.73 would be the mistake this project is about.**

(The 0.65 row is honest only in that 0.65 came from a stated rule — min − 1 SD — not from scanning
the sweep for a winner. It is still estimated from these 66 answerable scores, so treat 78.2% as an
upper bound, not a measurement. See "what this is not evidence for" below.)

### What this analysis IS evidence for

These are properties of the *score distribution*, robust to which particular questions were asked:

1. **The classes are not separable by top-1 similarity on this corpus** — 77% of questions sit in the
   overlap. No sample of near-miss refusal questions would change this conclusion; it follows from
   what cosine similarity measures.
2. **The current floor of 0.55 costs nothing.** Zero false refusals, and there is provably no
   answerable question anywhere near it. It is not broken — it is just idle, and it was picked for
   the right reason (well below the answerable mass) from the wrong evidence (3 documents).
3. **Raising the floor into the overlap is a losing trade at every step.** From 0.73 upward, each
   additional refusal caught costs more than one false refusal, and the ratio worsens monotonically.
4. **Gate 1 can carry at most ~2/21 of the refusals here**, so gate 2 is not a backstop — it is the
   primary refusal mechanism, and should be evaluated as such.

### What it is NOT evidence for

1. **That 0.65 is optimal.** It is a defensible, conservative value from a stated rule. There is no
   measurement here that establishes an optimum, and §6's CV shows the search for one backfires.
2. **Any refusal metric for floor 0.65 reported against these same 87 questions.** If 0.65 is
   applied, the refusal recall / FRR / precision in the comparison table of `docs/EVAL.md` are
   **in-sample numbers for a threshold fitted in-sample**, and must be footnoted as such or the
   baseline row is contaminated for every later phase that compares against it.
3. **Anything about production.** 20/21 refusals here are adversarial near-misses. Real users ask
   "capital of France"-shaped questions far more often, so this set *understates* how much work the
   floor does in the wild — another reason not to tune it aggressively against this distribution.

### A non-circular procedure

1. **Write a separate calibration set** — `eval/calibration.yaml`, ~30–40 new questions in the same
   three classes, same authoring rules (including near-miss refusals), **never scored in the
   comparison table**. Derive the floor there; report on the 87. This is the clean fix and the only
   one that keeps the baseline row honest.
2. **If a new set is too expensive, use a stratified hold-out split** — freeze e.g. 26 questions
   (10/10/6) as calibration-only, tune on those, report on the remaining 61. Cheaper, but it shrinks
   the reporting set, and on 61 questions one question is 1.6 points.
3. **Report the CV number, not the fitted one.** Whatever the procedure, the number that belongs
   next to a tuned threshold is its held-out accuracy (75.2% for accuracy-tuning above), not its
   in-sample accuracy (79.3%). The gap is the finding.
4. **Pre-register the rule, not the value.** "Floor = min(answerable) − 1 SD, on the calibration
   set" is a rule that survives a change of embedder and can be re-run mechanically in Phase 2/3
   when reranking and fusion change the score scale. A hand-picked constant cannot.

**Recommendation, restated with its caveat:** set `retrieval.floor` to **0.65** — a small, safe
correction to a provisional value, justified by a stated rule rather than by a sweep result, that
changes one question out of 87. Do not report it as a tuned improvement. The real finding of this
analysis is that **the floor is not where refusal quality lives on this corpus**, and the next
measurement worth making is gate 2's recall on the 19 near-misses the floor will never catch.

---

### Reproducing

All numbers derive from `eval/runs/baseline.jsonl` alone (no LLM calls, no re-running `eval`):
per-row `top_score` and `cls`, with `passed_floor` verified consistent with `top_score >= 0.55` on
all 87 rows. Sweep definitions as given in §3; bootstrap 5000 resamples, CV 5-fold × 200 reps,
seeded.
