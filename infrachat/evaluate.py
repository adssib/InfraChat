"""F11 — the eval harness: the fixed question set in, a comparable run out.

This module is the project's quality gate (ADR-0003). It exists so that *"the reranker
improved retrieval"* is a number measured on identical inputs rather than an impression,
and every design choice here serves comparability:

- **It reads the pipeline, it does not reimplement it.** `retrieve()` and `answer_query()`
  are called exactly as `ask` calls them, so an eval run exercises the shipped code path
  including both gates. A harness with its own retrieval loop would measure itself.
- **It changes nothing.** No config is written back, no component is swapped, nothing is
  cached between questions. The only inputs are `cfg` and `deps`; the phase under test is
  whatever `deps` was built with, labelled by `cfg.eval.run_label`.
- **Every number carries its denominator.** docs/EVAL.md § Reading the results honestly:
  on a 30-question set one question is 3.3 points, so a metric without its `n` invites a
  false claim. Each group in the summary reports its own `n`.
- **Per-question rows are written before they are aggregated.** A run that dies on
  question 24 (free-tier rate limit) still leaves 23 usable rows, and a question that
  raises is recorded as an error rather than quietly scored as a refusal.

Two modes, one function. With `deps.llm is None` it scores the retrieval half only —
hit-rate, MRR, latency — and needs no API key, which is what makes the question set
debuggable before the generator is wired. With a generator it also scores grounding,
refusal and cost.

Known limits, stated rather than hidden:

- **Token counts are estimates.** The `LLMClient` seam returns text, not usage, so the
  counting wrapper here measures characters and divides by four. Fields are suffixed
  `_est` for that reason. A true count means adding usage to the seam — a contract
  change, not something to slip in.
- `answer_query()` does not hand back the retrieval it used, so a question that reaches
  the generator embeds and searches twice: once here for the retrieval metrics, once
  inside the pipeline. The cost is one ANN query; the alternative is either duplicating
  the pipeline or widening its return type, and both are worse than a few milliseconds.
  Reported latency is the pipeline call only, never the metrics call. This assumes the two
  retrievals agree, which holds while every stage is deterministic — `answer/llm.py` pins
  `temperature=0` for exactly that reason. A sampling Phase 4 rewriter would break the
  assumption, and the citation metric (which checks against the tags the *first* retrieval
  offered) would be the first thing to go wrong.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from infrachat.answer.citations import parse_tag_candidates
from infrachat.answer.prompt import offered_tags
from infrachat.config import Config
from infrachat.models import Answer
from infrachat.pipeline import Deps, Retrieval, answer_query, retrieve

#: The three classes from docs/EVAL.md § The question set. A fourth would change what the
#: ratios mean, so an unknown class is an error rather than an extra bucket.
CLASSES = ("k8s-answerable", "docker-answerable", "should-refuse")

#: Characters per token. Crude on purpose — see the module docstring on `_est`.
_CHARS_PER_TOKEN = 4


# --------------------------------------------------------------------- question set


@dataclass(frozen=True)
class Question:
    """One row of `eval/questions.yaml`, validated.

    `expect_sources` is a set even when the YAML names one doc set: the both-source case
    (docs/EVAL.md — *"check the citation names whichever it actually used"*) needs several
    answers to be correct, and collapsing that into a single string at load time would
    push the special case into every metric.
    """

    id: str
    question: str
    cls: str
    expect_sources: frozenset[str]
    expect_docs: tuple[str, ...]
    tags: tuple[str, ...] = ()
    note: str = ""

    @property
    def answerable(self) -> bool:
        return self.cls != "should-refuse"


def load_questions(path: Path, valid_sources: Iterable[str] = ()) -> list[Question]:
    """Parse and validate the question set, in file order.

    Order is preserved because docs/EVAL.md pins it: the same questions in the same order
    every phase, so two JSONL files can be diffed row by row.

    Validation is strict because every mistake here is *silent*. A typo in `expect_docs`
    is a permanent miss that reads as a retrieval failure; a `should-refuse` entry with
    an `expect_source` would count a correct refusal as a wrong citation. Those are the
    exact failure mode CLAUDE.md reserves tests for, so they raise instead.
    """
    raw = yaml.safe_load(path.read_text()) or {}
    entries = raw.get("questions")
    if not entries:
        raise ValueError(f"{path}: no questions defined under `questions:`")

    valid = set(valid_sources)
    questions: list[Question] = []
    for i, entry in enumerate(entries):
        where = f"{path}: question {i + 1}"
        qid = entry.get("id")
        if not qid:
            raise ValueError(f"{where}: missing `id`")
        where = f"{path}:{qid}"

        text = (entry.get("question") or "").strip()
        if not text:
            raise ValueError(f"{where}: missing `question`")

        cls = entry.get("class")
        if cls not in CLASSES:
            raise ValueError(f"{where}: class {cls!r} is not one of {CLASSES}")

        src = entry.get("expect_source")
        sources = frozenset(src if isinstance(src, list) else [] if src is None else [src])
        docs = tuple(entry.get("expect_docs") or ())

        if cls == "should-refuse":
            if sources or docs:
                raise ValueError(
                    f"{where}: a should-refuse question must have `expect_source: null` "
                    f"and `expect_docs: []` — there is no correct citation to check"
                )
        else:
            if not docs:
                raise ValueError(
                    f"{where}: an answerable question needs at least one expect_docs "
                    f"path, or hit-rate cannot be computed for it"
                )
            if not sources:
                raise ValueError(f"{where}: missing `expect_source`")
            unknown = sources - valid if valid else set()
            if unknown:
                raise ValueError(
                    f"{where}: expect_source {sorted(unknown)} is not a configured "
                    f"source; sources.yaml declares {sorted(valid)}"
                )

        questions.append(
            Question(
                id=qid,
                question=text,
                cls=cls,
                expect_sources=sources,
                expect_docs=docs,
                tags=tuple(entry.get("tags") or ()),
                note=(entry.get("note") or "").strip(),
            )
        )

    ids = [q.id for q in questions]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate question ids {dupes}")
    return questions


# --------------------------------------------------------------------- instrumentation


class _CountingLLM:
    """Wraps the generator to record what each call cost.

    A wrapper rather than a change to `LLMClient`: the pipeline stays unaware it is being
    measured, and `ask` keeps the unwrapped client. It counts calls made *through
    `deps.llm`*, which in Phase 1 is the generator only. A Phase 4 rewriter that holds its
    own client will need its own wrapper — its tokens are not counted here, and the
    summary says so rather than under-reporting silently.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, int]] = []

    def complete(self, system: str, user: str) -> str:
        text = self._inner.complete(system, user)
        self.calls.append(
            {
                "prompt_chars": len(system) + len(user),
                "completion_chars": len(text),
            }
        )
        return text

    def drain(self) -> dict[str, int]:
        """Totals since the last drain, then reset — one question's cost."""
        prompt = sum(c["prompt_chars"] for c in self.calls)
        completion = sum(c["completion_chars"] for c in self.calls)
        n = len(self.calls)
        self.calls = []
        return {
            "llm_calls": n,
            "prompt_tokens_est": _tokens(prompt),
            "completion_tokens_est": _tokens(completion),
            "total_tokens_est": _tokens(prompt) + _tokens(completion),
        }


def _tokens(chars: int) -> int:
    return math.ceil(chars / _CHARS_PER_TOKEN)


# --------------------------------------------------------------------- per-question


@dataclass
class Result:
    """One question's outcome — the shape of one JSONL row."""

    id: str
    cls: str
    question: str
    tags: list[str]
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    expect_docs: list[str] = field(default_factory=list)
    hit: bool | None = None              # None for should-refuse: nothing to hit
    first_rank: int | None = None
    reciprocal_rank: float | None = None
    top_score: float | None = None
    margin: float | None = None          # distance from floor; negative means refused
    passed_floor: bool | None = None
    refused: bool | None = None          # None when no generator ran
    refused_by: str | None = None        # "floor" (F8) | "citation" (F9) | None
    citations: list[str] = field(default_factory=list)   # tags the answer carried
    cited_tags: list[str] = field(default_factory=list)  # tags parsed from the text
    invalid_tags: list[str] = field(default_factory=list)
    citation_valid: bool | None = None
    cited_sources: list[str] = field(default_factory=list)
    source_ok: bool | None = None
    answer_chars: int | None = None
    latency_ms: float | None = None
    retrieval_ms: float | None = None
    llm_calls: int | None = None
    prompt_tokens_est: int | None = None
    completion_tokens_est: int | None = None
    total_tokens_est: int | None = None
    error: str | None = None

    def row(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _score_retrieval(q: Question, r: Retrieval, res: Result) -> None:
    """Fill in hit-rate and MRR inputs from what retrieval produced.

    Reads `r.hits`, not `r.decision.hits`: the gate empties its list on a refusal, and
    *did retrieval find it* is a separate question from *was it confident enough*. Mixing
    them would make a floor change look like a retrieval change.
    """
    res.retrieved = [
        {
            "rank": i,
            "chunk_id": h.chunk.id,
            "source": h.chunk.source,
            "doc": h.chunk.source_doc,
            "location": h.chunk.source_location,
            "score": round(h.score, 4),
        }
        for i, h in enumerate(r.hits, 1)
    ]
    res.top_score = None if r.decision.top_score is None else round(r.decision.top_score, 4)
    res.margin = None if r.decision.margin is None else round(r.decision.margin, 4)
    res.passed_floor = r.decision.passed

    if not q.answerable:
        return

    expected = set(q.expect_docs)
    ranks = [i for i, h in enumerate(r.hits, 1) if h.chunk.source_doc in expected]
    res.first_rank = ranks[0] if ranks else None
    res.hit = bool(ranks)
    res.reciprocal_rank = 1.0 / ranks[0] if ranks else 0.0


def _score_answer(q: Question, r: Retrieval, answer: Answer, cfg: Config, res: Result) -> None:
    """Fill in grounding and refusal outcomes from the Answer."""
    res.refused = not answer.grounded
    res.answer_chars = len(answer.text)

    if res.refused:
        # Which gate did the work matters: F8 is free and model-free, F9 costs a call.
        # A phase that shifts refusals from one to the other changed the economics even
        # if the headline refusal rate is flat (docs/EVAL.md § Watch the gate).
        res.refused_by = "floor" if not r.decision.passed else "citation"
        return

    max_chunks = cfg.require_llm().max_context_chunks
    offered = offered_tags(r.decision.hits, max_chunks)

    # Parsed from the text, not taken from answer.citations: `citations.verify` already
    # dropped anything unmatched, so reading its output back would score 100% by
    # construction. The interesting failure is a valid citation sitting next to an
    # invented one — an answer that is grounded but partly fabricated.
    res.cited_tags = parse_tag_candidates(answer.text)
    res.invalid_tags = [t for t in res.cited_tags if t not in offered]
    res.citation_valid = bool(res.cited_tags) and not res.invalid_tags

    res.citations = [c.tag for c in answer.citations]
    res.cited_sources = sorted({c.source for c in answer.citations})
    if q.answerable:
        # F10, strictly: every citation must name a doc set that can answer this
        # question. One stray citation from the other doc set is the confusion the
        # metric exists to catch, so it fails the question rather than averaging away.
        res.source_ok = bool(res.cited_sources) and all(
            s in q.expect_sources for s in res.cited_sources
        )


def _evaluate_one(q: Question, cfg: Config, deps: Deps, counter: _CountingLLM | None) -> Result:
    res = Result(id=q.id, cls=q.cls, question=q.question, tags=list(q.tags),
                 expect_docs=list(q.expect_docs))

    t0 = time.perf_counter()
    r = retrieve(q.question, cfg, deps)
    res.retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)
    _score_retrieval(q, r, res)

    if deps.llm is None:
        res.latency_ms = res.retrieval_ms      # retrieval-only: the whole query is this
        return res

    t1 = time.perf_counter()
    answer = answer_query(q.question, cfg, deps)
    res.latency_ms = round((time.perf_counter() - t1) * 1000, 1)
    _score_answer(q, r, answer, cfg, res)

    if counter is not None:
        res.__dict__.update(counter.drain())
    return res


# --------------------------------------------------------------------- aggregation


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _pct(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile.

    Not interpolated: on 30 samples an interpolated p95 is a weighted average of two
    observations and reads as more precise than it is. This returns a latency that was
    actually measured.
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[idx], 1)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _summarise(rows: Sequence[Result], cfg: Config, *, with_llm: bool) -> dict[str, Any]:
    """Every metric docs/EVAL.md § Metrics defines, each with its denominator."""
    k = cfg.retrieval.k
    ok = [r for r in rows if r.error is None]
    answerable = [r for r in ok if r.cls != "should-refuse"]
    should_refuse = [r for r in ok if r.cls == "should-refuse"]

    summary: dict[str, Any] = {
        "questions": len(rows),
        "scored": len(ok),
        "errors": len(rows) - len(ok),
        "retrieval": {
            "n": len(answerable),
            f"hit_rate_at_{k}": _rate(sum(1 for r in answerable if r.hit), len(answerable)),
            "mrr": _mean([r.reciprocal_rank for r in answerable
                          if r.reciprocal_rank is not None]),
        },
    }

    latencies = [r.latency_ms for r in ok if r.latency_ms is not None]
    summary["cost"] = {
        "n": len(latencies),
        "p50_latency_ms": _pct(latencies, 0.50),
        "p95_latency_ms": _pct(latencies, 0.95),
        "max_latency_ms": round(max(latencies), 1) if latencies else None,
    }

    if not with_llm:
        # Retrieval-only: report what the floor alone would have decided, and say plainly
        # that the grounding metrics were not measured. An omitted metric and a zero are
        # very different facts about a run.
        summary["grounding"] = None
        summary["refusal"] = {
            "n": len(ok),
            "note": "retrieval-only run: floor (F8) outcomes only, no generator",
            "floor_refusals": sum(1 for r in ok if r.passed_floor is False),
            "recall_floor_only": _rate(
                sum(1 for r in should_refuse if r.passed_floor is False), len(should_refuse)
            ),
            "false_refusal_rate_floor_only": _rate(
                sum(1 for r in answerable if r.passed_floor is False), len(answerable)
            ),
        }
        summary["by_class"] = _breakdown(ok, k, key=lambda r: r.cls, with_llm=False)
        summary["by_tag"] = _breakdown(ok, k, key=None, with_llm=False)
        summary["misses"] = [r.id for r in answerable if r.hit is False]
        return summary

    answered = [r for r in answerable if r.refused is False]
    grounded = [r for r in ok if r.refused is False]
    refusals = [r for r in ok if r.refused]

    summary["grounding"] = {
        "n_answers": len(grounded),
        "citation_validity": _rate(sum(1 for r in grounded if r.citation_valid), len(grounded)),
        "n_answers_answerable": len(answered),
        "source_accuracy": _rate(sum(1 for r in answered if r.source_ok), len(answered)),
    }
    summary["refusal"] = {
        "n_should_refuse": len(should_refuse),
        "n_answerable": len(answerable),
        "n_refusals": len(refusals),
        "recall": _rate(sum(1 for r in should_refuse if r.refused), len(should_refuse)),
        "precision": _rate(sum(1 for r in refusals if r.cls == "should-refuse"), len(refusals)),
        "false_refusal_rate": _rate(sum(1 for r in answerable if r.refused), len(answerable)),
        "by_gate": dict(Counter(r.refused_by for r in refusals if r.refused_by)),
    }

    tokens = [r.total_tokens_est for r in ok if r.total_tokens_est is not None]
    summary["cost"].update(
        {
            "mean_total_tokens_est": _mean(tokens),
            "mean_prompt_tokens_est": _mean([r.prompt_tokens_est for r in ok
                                             if r.prompt_tokens_est is not None]),
            "mean_completion_tokens_est": _mean([r.completion_tokens_est for r in ok
                                                 if r.completion_tokens_est is not None]),
            "llm_calls": sum(r.llm_calls or 0 for r in ok),
            "tokens_note": "estimated from characters / 4 — the LLMClient seam returns "
                           "no usage; a rewriter with its own client is not counted",
        }
    )

    summary["by_class"] = _breakdown(ok, k, key=lambda r: r.cls, with_llm=True)
    summary["by_tag"] = _breakdown(ok, k, key=None, with_llm=True)
    summary["misses"] = [r.id for r in answerable if r.hit is False]
    summary["wrong_source"] = [r.id for r in answered if r.source_ok is False]
    summary["fabrications"] = [r.id for r in should_refuse if r.refused is False]
    summary["false_refusals"] = [r.id for r in answerable if r.refused]
    return summary


def _breakdown(rows: Sequence[Result], k: int, *, key, with_llm: bool) -> dict[str, Any]:
    """Per-class or per-tag slices.

    docs/EVAL.md § Reading the results honestly: *"hybrid may be flat overall and decisive
    on exact-term questions — the aggregate would hide the single most interesting finding
    in the project."* A tagged question belongs to several slices at once, which is why
    tags are a list and the shares inside `by_tag` do not sum to 1.
    """
    groups: dict[str, list[Result]] = {}
    if key is None:
        for r in rows:
            for tag in r.tags:
                groups.setdefault(tag, []).append(r)
    else:
        for r in rows:
            groups.setdefault(key(r), []).append(r)

    out: dict[str, Any] = {}
    for name, group in sorted(groups.items()):
        answerable = [r for r in group if r.cls != "should-refuse"]
        block: dict[str, Any] = {"n": len(group)}
        if answerable:
            block[f"hit_rate_at_{k}"] = _rate(
                sum(1 for r in answerable if r.hit), len(answerable)
            )
            block["mrr"] = _mean([r.reciprocal_rank for r in answerable
                                  if r.reciprocal_rank is not None])
        if with_llm:
            refusals = [r for r in group if r.refused]
            block["refusals"] = len(refusals)
            if answerable:
                block["false_refusal_rate"] = _rate(
                    sum(1 for r in answerable if r.refused), len(answerable)
                )
                answered = [r for r in answerable if r.refused is False]
                if answered:
                    block["source_accuracy"] = _rate(
                        sum(1 for r in answered if r.source_ok), len(answered)
                    )
            else:
                block["recall"] = _rate(len(refusals), len(group))
        latencies = [r.latency_ms for r in group if r.latency_ms is not None]
        block["p95_latency_ms"] = _pct(latencies, 0.95)
        out[name] = block
    return out


# --------------------------------------------------------------------- run provenance


def _git_commit(path: Path) -> str | None:
    """The commit of the clone a source was ingested from, or None.

    docs/EVAL.md pins the corpus commit because the upstream docs move: without it a
    phase-to-phase delta could be Kubernetes shipping a new page. Recorded as `null` when
    it cannot be read, never as a guess.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _index_stats(deps: Deps) -> dict[str, int] | None:
    """Chunk counts, if the retriever happens to expose its store.

    Deliberately duck-typed and optional: the `Retriever` protocol promises `retrieve()`
    and nothing else, and a Phase 3 hybrid arm may not own a single store. Useful header
    provenance, never a requirement.
    """
    store = getattr(deps.retriever, "store", None)
    stats = getattr(store, "stats", None)
    if not callable(stats):
        return None
    try:
        return {**store.stats(), "per_source": store.per_source()}
    except Exception:
        return None


def _header(cfg: Config, deps: Deps, questions: Sequence[Question], root: Path) -> dict[str, Any]:
    """The JSONL's first line: everything needed to say whether two runs are comparable.

    docs/EVAL.md § Where results land requires the corpus commit, embedder, generator
    model and date. The rest is here because a reviewer reading one file should not have
    to find the config that produced it: the question-set digest proves the set was
    unchanged, and the component flags name which seam this run swapped.
    """
    question_set = _resolve(cfg.eval.question_set, root)
    return {
        "record": "header",
        "run_label": cfg.eval.run_label,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": len(questions),
        "questions_by_class": dict(Counter(q.cls for q in questions)),
        "question_set": str(cfg.eval.question_set),
        "question_set_sha256": hashlib.sha256(question_set.read_bytes()).hexdigest()[:12],
        "corpus": [
            {
                "source": s.name,
                "path": str(s.path),
                "commit": _git_commit(root / s.path),
            }
            for s in cfg.sources
        ],
        "index": _index_stats(deps),
        "embedder": cfg.embedder.model,
        "chunk": {"size": cfg.chunk.size, "overlap": cfg.chunk.overlap},
        "retrieval": {
            "retrieve_n": cfg.retrieval.retrieve_n,
            "k": cfg.retrieval.k,
            "floor": cfg.retrieval.floor,
        },
        "generator": None if cfg.llm is None or deps.llm is None else {
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "max_context_chunks": cfg.llm.max_context_chunks,
            "temperature": 0,
        },
        "components": {
            "rewrite": cfg.rewrite.enabled,
            "rerank": cfg.rerank.enabled,
            "hybrid": cfg.retrieval.hybrid.enabled,
        },
        "host": {"python": sys.version.split()[0]},
    }


def _resolve(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


# --------------------------------------------------------------------- entry point


def run(cfg: Config, deps: Deps, *, root: Path | None = None,
        progress: bool = True) -> dict[str, Any]:
    """Run the fixed question set and return the summary.

    `deps` decides what is being measured — Phase 1 passes the null objects, a later phase
    passes a real reranker or hybrid retriever. The harness never builds or inspects them,
    so adding a component cannot require a change here.

    Results land in `cfg.eval.results_dir/<run_label>.jsonl`: one header line, then one
    row per question in question-set order. The file is written to a temporary path and
    moved into place, so a crashed or rate-limited run cannot truncate a committed
    baseline.

    Returns the summary dict (also the value `cli.py` prints); `format_summary` renders it.
    """
    root = (root or Path.cwd()).resolve()
    questions = load_questions(_resolve(cfg.eval.question_set, root), cfg.source_names)

    counter: _CountingLLM | None = None
    if deps.llm is not None:
        counter = _CountingLLM(deps.llm)
        deps = replace(deps, llm=counter)       # a copy: the caller's Deps is untouched

    results_dir = _resolve(cfg.eval.results_dir, root)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{cfg.eval.run_label}.jsonl"
    tmp_path = out_path.with_suffix(".jsonl.partial")

    header = _header(cfg, deps, questions, root)
    rows: list[Result] = []
    _warm_up(deps)
    started = time.monotonic()

    if progress:
        model = getattr(cfg.llm, "model", "unknown")
        mode = "retrieval-only" if deps.llm is None else f"generator {model}"
        print(f"eval `{cfg.eval.run_label}` · {len(questions)} questions · {mode}")

    with tmp_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        fh.flush()

        for i, q in enumerate(questions, 1):
            try:
                res = _evaluate_one(q, cfg, deps, counter)
            except Exception as exc:                      # noqa: BLE001 — see below
                # One question must not cost the other 29. A free-tier rate limit, a
                # dropped connection or a provider 500 is recorded as an error and
                # excluded from every denominator, because scoring it as a refusal would
                # silently improve refusal recall.
                res = Result(id=q.id, cls=q.cls, question=q.question, tags=list(q.tags),
                             expect_docs=list(q.expect_docs),
                             error=f"{type(exc).__name__}: {exc}")
                if counter is not None:
                    counter.drain()
            rows.append(res)
            fh.write(json.dumps(res.row()) + "\n")
            fh.flush()
            if progress:
                print(f"  [{i:>2}/{len(questions)}] {_progress_line(res)}")

    tmp_path.replace(out_path)

    summary = _summarise(rows, cfg, with_llm=deps.llm is not None)
    summary["run_label"] = cfg.eval.run_label
    summary["results_path"] = str(out_path)
    summary["elapsed_s"] = round(time.monotonic() - started, 1)
    summary["header"] = header
    return summary


def _warm_up(deps: Deps) -> None:
    """One throwaway retrieval before the clock starts.

    The embedder loads its ONNX model on first use, so without this the first question
    carries ~200ms of model load and p95 latency reports a one-off cost as a query cost.
    Deliberately `retriever.retrieve()` and not `pipeline.retrieve()`: the `Retriever`
    protocol promises that method, while the full pipeline would put a Phase 4 rewriter's
    LLM call in the warm-up and spend real tokens on a discarded query.
    """
    try:
        deps.retriever.retrieve("warm-up", 1)
    except Exception:      # a warm-up failure is not a run failure; the real call reports it
        pass


def _progress_line(res: Result) -> str:
    if res.error:
        return f"{res.id:<34} ERROR {res.error}"
    if res.refused is None:
        verdict = "floor-pass" if res.passed_floor else "floor-refuse"
    elif res.refused:
        verdict = f"refused({res.refused_by})"
    else:
        verdict = "answered"
    rank = "-" if res.first_rank is None else f"@{res.first_rank}"
    score = "—" if res.top_score is None else f"{res.top_score:.3f}"
    return f"{res.id:<34} {verdict:<18} top1={score} hit{rank} {res.latency_ms:.0f}ms"


# --------------------------------------------------------------------- presentation


def format_summary(summary: dict[str, Any]) -> str:
    """Render the summary for a terminal.

    Lives here, not in `cli.py`, so the numbers and their labels stay together: a metric
    renamed in one place and not the other is how a comparison table starts lying. Every
    line carries its `n` for the reason docs/EVAL.md gives — one question out of 30 is 3.3
    points, and most deltas smaller than that are noise.
    """
    h = summary.get("header", {})
    lines: list[str] = []
    lines.append("")
    lines.append(f"run `{summary['run_label']}`  ·  {summary['questions']} questions  "
                 f"·  {summary['elapsed_s']}s")
    corpus = "  ".join(
        f"{c['source']}@{(c['commit'] or 'unknown')[:8]}" for c in h.get("corpus", [])
    )
    gen = h.get("generator")
    lines.append(f"  corpus    {corpus or 'unknown'}")
    lines.append(f"  embedder  {h.get('embedder')}  ·  chunk "
                 f"{h.get('chunk', {}).get('size')}/{h.get('chunk', {}).get('overlap')}"
                 f"  ·  k={h.get('retrieval', {}).get('k')}"
                 f"  floor={h.get('retrieval', {}).get('floor')}")
    lines.append(f"  generator {gen['model'] if gen else '(none — retrieval-only run)'}")
    lines.append(f"  questions {h.get('questions_by_class')}"
                 f"  ·  set {h.get('question_set_sha256')}")
    if summary["errors"]:
        lines.append(f"  ERRORS    {summary['errors']} question(s) failed — this run is "
                     f"not comparable until they are re-run")

    def block(title: str, body: dict[str, Any], skip: Iterable[str] = ()) -> None:
        lines.append("")
        lines.append(title)
        for key, value in body.items():
            if key in skip or isinstance(value, dict):
                continue
            lines.append(f"  {key:<30} {value}")

    block("RETRIEVAL", summary["retrieval"])
    if summary.get("grounding"):
        block("GROUNDING", summary["grounding"])
    block("REFUSAL", summary["refusal"])
    lines.append(f"  by_gate                        {summary['refusal'].get('by_gate', {})}")
    block("COST", summary["cost"])

    for title, key in (("BY CLASS", "by_class"), ("BY TAG", "by_tag")):
        lines.append("")
        lines.append(title)
        for name, stats in summary.get(key, {}).items():
            rendered = "  ".join(f"{k}={v}" for k, v in stats.items())
            lines.append(f"  {name:<20} {rendered}")

    for label, key in (
        ("misses (retrieval found no expected doc)", "misses"),
        ("wrong source cited", "wrong_source"),
        ("fabricated instead of refusing", "fabrications"),
        ("falsely refused", "false_refusals"),
    ):
        ids = summary.get(key)
        if ids:
            lines.append("")
            lines.append(f"{label}: {', '.join(ids)}")

    lines.append("")
    lines.append(f"wrote {summary['results_path']}")
    return "\n".join(lines)
