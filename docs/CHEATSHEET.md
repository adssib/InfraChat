# InfraChat Cheatsheet

Plain-English definitions of every term and metric in this project, with the InfraChat numbers and a line to say in an interview.

---

## Part 1: How the system works (the pipeline)

| Term | What it means | Say it like this |
|---|---|---|
| **RAG** (Retrieval-Augmented Generation) | Before the LLM answers, you **search your documents** and paste the best matches into the prompt. The LLM answers from those, not from memory. | "The model answers from the retrieved docs, not from its training data." |
| **Corpus** | The pile of documents you search. | "281 Kubernetes and Docker doc files." |
| **Chunk** | A small piece of a document, about 800 characters. You search chunks, not whole files, because a whole file is too big to paste into the prompt. | "4,908 chunks, 800 characters each with 100 of overlap." |
| **Overlap** | Neighbouring chunks share some text, so an answer sitting on a boundary isn't cut in half. | "My overlap was silently broken on 59% of boundaries. Fixing it took paraphrase MRR from 0.39 to 0.70." |
| **Embedding** | Turning text into a list of numbers (384 of them) so that similar *meanings* get similar numbers. "Remove a container" and "delete a container" land close together. | "bge-small, a small embedding model that runs on CPU." |
| **Cosine similarity** | A score from about 0 to 1 for how close two embeddings are. 1 means the same meaning. | "The best chunk for the sourdough question scored 0.65." |
| **Dense retrieval** (vector search) | Search by **meaning** using embeddings. Good at paraphrases, bad at exact names like `depends_on`. | "Dense search finds meaning but misses exact terms." |
| **BM25** (keyword search) | Classic search by **matching words**. Good at exact terms, bad at paraphrases. | "BM25 catches exact flags and config keys." |
| **Hybrid search** | Run both searches and merge the results. | "Hybrid got 71% of the reranker's gain for 6 ms." |
| **RRF** (Reciprocal Rank Fusion) | How the two result lists get merged: each chunk gets 1/(60 + its rank) from each list, and the scores are added. It uses only rank positions, never raw scores, so the two scales don't need to match. | "RRF merges by rank, so I didn't have to calibrate scores." |
| **Reranker** (cross-encoder) | A second, slower model that reads the question **and** each chunk *together* and re-sorts the top results. More accurate, but costs 800+ ms. | "A cross-encoder reads question and chunk jointly, so it's more precise and much slower." |
| **Bi-encoder vs cross-encoder** | A bi-encoder (the embedder) encodes the question and the chunk *separately*, so it's fast. A cross-encoder encodes them *together*, so it's slow and accurate. | Only if they ask. |
| **Query rewriting** | Ask an LLM to rephrase or expand the question before searching. | "It cost an LLM call per query for about one extra correct question, so I didn't ship it." |
| **Floor / threshold** (Gate 1) | If even the best chunk scores below 0.65, refuse. | "A cheap first filter. It can't be the real classifier." |
| **Citation check** (Gate 2) | The answer must cite chunks that were actually shown to the model, or it gets refused. | "22 of 24 refusals came from the citation gate." |
| **Refusal** | The system says "not in the docs" instead of guessing. | "A wrong answer about infrastructure is worse than no answer." |

---

## Part 2: The metrics

### hit@5
**"Was the right document anywhere in the top 5 results?"** Yes or no per question, then averaged.

- Baseline: **0.969**. The right doc was in the top 5 for about 64 of 66 answerable questions.
- Say it: *"Retrieval almost always finds the right doc. The question is whether it ranks it first."*

### MRR (Mean Reciprocal Rank)
**"How high up was the first right result?"**

| Right doc appears at… | Score |
|---|---|
| Rank 1 | 1 |
| Rank 2 | 1/2 = 0.5 |
| Rank 3 | 1/3 = 0.33 |
| Rank 4 | 0.25 |
| Not found | 0 |

Score every question this way, then take the average.

**Example with 3 questions:** right doc at rank 1, rank 2 and rank 1 → (1 + 0.5 + 1) / 3 = **0.83**.

- InfraChat: baseline **0.795** → reranker **0.877** → hybrid **0.858**.
- Rough intuition: 0.8 means "usually first, sometimes second".
- Say it: *"MRR rewards putting the right document first, not just somewhere in the list."*

### Precision vs recall
Think of a **spam filter**:

- **Precision:** of the emails I flagged as spam, how many really were spam? This asks whether I'm **wrongly** accusing.
- **Recall:** of all the real spam, how much did I catch? This asks whether I'm **missing** things.

Now replace "spam" with "questions that should be refused":

| Metric | Question it asks | Baseline | The math |
|---|---|---|---|
| **Refusal recall** | Of the 21 questions that *should* be refused, how many did we refuse? | **0.952** | 20 of 21 |
| **Refusal precision** | Of everything we refused, how many *deserved* it? | **0.833** | 20 of 24 |
| **False-refusal rate** | Of the answerable questions, how many did we wrongly refuse? | **0.062** (6.2%) | 4 of about 65 |

- **Reranker:** recall dropped to **0.857** (18 of 21). It stopped refusing 3 of the questions it should have refused, and 2 of those turned into made-up answers.
- **Hybrid:** recall stayed at **0.952**, false refusals halved to **3.1%** (2 questions), and precision rose to **0.909** (20 of 22).
- Say it: *"Recall is 'did we refuse the traps'. Precision is 'did we only refuse the traps'."*

### Citation validity
**"Did every citation point to a chunk that was actually shown to the model?"** Baseline: **1.000**, meaning no invented citations across 62 answers.

> ⚠️ This does **not** mean the answer is true. See *provenance vs entailment* below.

### Source accuracy
**"Did it cite the right product?"** Kubernetes docs for a Kubernetes question, Docker docs for a Docker question. Baseline: **0.984**.

### p50 latency
**"The median response time."** Half of queries are faster than this, half are slower. Baseline: about **9 s**, mostly the LLM. p95 means 95% of queries are faster than that number.

---

## Part 3: The concepts

| Term | Plain meaning | Your example |
|---|---|---|
| **Baseline** | The simplest version, measured first so every change has something to be compared against. | "Dense search only, MRR 0.795." |
| **Ablation** | Add or remove **one component at a time** to see what it's worth. | "I toggled reranker, hybrid and rewriter one at a time from config." |
| **Eval set** | A fixed list of questions with known right answers, reused on every run. | "87 questions, 21 of them designed to be refused." |
| **Near-miss question** | An unanswerable question built to *look* answerable. | "'How do I bake sourdough?' scored 0.648 because of Docker Bake — the floor caught it by 0.002." |
| **Overfitting** | Tuning a setting so it fits your test questions and then fails on new ones. | "Threshold 0.73 scored 79% fitted but only 75% held out." |
| **Cross-validation** | Tune on part of the questions, test on the rest, rotate, and average. It shows how much your tuning is lying to you. | "5-fold CV showed about 4.4 points of optimism." |
| **Provenance vs entailment** | **Provenance:** the cited doc was really shown to the model. **Entailment:** the doc actually *supports* the claim. | "My gate checks provenance. The reranker's fabrications had valid citations but false claims." |
| **NLI** (Natural Language Inference) | A small model that checks "does text A support claim B?" It's the fix for entailment. | "The next step is an NLI check on each cited sentence." |
| **Tokens / TPD** | LLMs bill by tokens (about ¾ of a word). TPD means tokens per day. | "The free tier allows 200K tokens a day, about one full eval, so I built `--resume`." |
| **Temperature 0** | The LLM makes the same choice every time, as close to deterministic as possible. | "Temperature 0 so runs are comparable." |
| **Reasoning model** | An LLM that "thinks" before answering, using hidden tokens. | "gpt-oss-20b sometimes spent all its tokens thinking and returned nothing. I made that an error instead of a refusal." |
| **ONNX** | A format for running ML models fast on CPU without PyTorch. | "No PyTorch, so the Docker image stays small." |
| **FTS5 / sqlite-vec** | SQLite's built-in keyword search, and an extension that adds vector search. | "Keyword and vector search in one SQLite file." |
| **ADR** (Architecture Decision Record) | A short doc: what we decided, why, and what we gave up. | "11 ADRs, for example ADR-0011: ship hybrid, not the reranker." |

---

## Part 4: Quiz yourself

<details><summary>1. Right doc at ranks 1, 4 and "not found". What's the MRR?</summary>

(1 + 0.25 + 0) / 3 = **0.42**
</details>

<details><summary>2. Why did the reranker get the better MRR but not get shipped?</summary>

It lowered refusal recall from 0.952 to 0.857 and fabricated 2 answers.
</details>

<details><summary>3. What's the difference between refusal recall and refusal precision?</summary>

Catching the traps vs only refusing the traps.
</details>

<details><summary>4. Why can't the similarity floor alone decide refusals?</summary>

The classes overlap: 77% of questions sit in the overlap band, and the GitLab CI trap (0.834) outscores 48 of 66 answerable questions.
</details>

<details><summary>5. Citation validity is 1.000. Does that mean the answers are correct?</summary>

No. It proves provenance, not entailment.
</details>

<details><summary>6. Why hybrid over the reranker?</summary>

71% of the gain, 6 ms vs 821 ms, and no loss in refusal.
</details>
