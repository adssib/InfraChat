"""Render the results charts in docs/images/results/ from the committed eval runs.

    ./.venv/bin/python scripts/plot_results.py

Every number is recomputed from eval/runs/*.jsonl, paired the same way compare_runs.py
pairs them: only questions that completed without error in every run are scored, so a
question one arm failed on is excluded from all of them.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "results"
RUNS = {"baseline": "baseline.jsonl", "+reranker": "+reranker.jsonl", "+hybrid": "+hybrid.jsonl"}
# Validated with the dataviz palette checker (CVD + normal-vision separation, light surface).
COLORS = {"baseline": "#1baf7a", "+reranker": "#eb6834", "+hybrid": "#2a78d6"}
ANSWERABLE, REFUSE = "#2a78d6", "#e34948"
FLOOR = 0.65


def load(name: str) -> tuple[dict, dict[str, dict]]:
    lines = [json.loads(l) for l in (ROOT / "eval" / "runs" / name).read_text().splitlines() if l.strip()]
    header = next(l for l in lines if l.get("record") == "header")
    return header, {l["id"]: l for l in lines if "id" in l}


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def metrics(rows: dict[str, dict], ids: list[str]) -> dict[str, float]:
    ans = [q for q in ids if rows[q]["cls"] != "should-refuse"]
    ref = [q for q in ids if rows[q]["cls"] == "should-refuse"]
    refused_ref = sum(bool(rows[q]["refused"]) for q in ref)
    refused_ans = sum(bool(rows[q]["refused"]) for q in ans)
    return {
        "hit@5": mean([float(bool(rows[q]["hit"])) for q in ans]),
        "MRR": mean([rows[q]["reciprocal_rank"] or 0.0 for q in ans]),
        "refusal recall": refused_ref / len(ref),
        "refusal precision": refused_ref / (refused_ref + refused_ans),
        "false-refusal rate": refused_ans / len(ans),
    }


def style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)


def headline(runs: dict[str, dict], ids: list[str]) -> None:
    m = {n: metrics(r, ids) for n, r in runs.items()}
    keys = list(next(iter(m.values())))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    w = 0.26
    for i, name in enumerate(runs):
        xs = [k + (i - 1) * w for k in range(len(keys))]
        bars = ax.bar(xs, [m[name][k] for k in keys], w, label=name, color=COLORS[name])
        ax.bar_label(bars, fmt="%.3f", fontsize=7.5, padding=2)
    ax.set_xticks(range(len(keys)), [k + ("\n(lower is better)" if "false" in k else "") for k in keys])
    ax.set_ylim(0, 1.12)
    ax.legend(frameon=False, ncol=3, loc="upper right")
    style(ax, f"Headline metrics, paired on {len(ids)} questions")
    fig.tight_layout()
    fig.savefig(OUT / "headline-metrics.png", dpi=150)
    plt.close(fig)


def tradeoff(runs: dict[str, dict], ids: list[str]) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    base_ms = statistics.median(runs["baseline"][q]["retrieval_ms"] for q in ids)
    for name, rows in runs.items():
        m = metrics(rows, ids)
        extra = statistics.median(rows[q]["retrieval_ms"] for q in ids) - base_ms
        ax.scatter(max(extra, 1), m["MRR"], s=900 * m["refusal recall"] ** 6, color=COLORS[name],
                   alpha=0.85, edgecolor="white", linewidth=2, zorder=3)
        ax.annotate(f"{name}\nMRR {m['MRR']:.3f} · refusal recall {m['refusal recall']:.3f}\n"
                    f"+{max(extra, 0):.0f} ms retrieval",
                    (max(extra, 1), m["MRR"]), xytext=(14, -6), textcoords="offset points", fontsize=8.5)
    ax.set_xscale("log")
    ax.set_xlim(0.6, 30000)
    ax.set_ylim(0.78, 0.9)
    ax.set_xlabel("extra median retrieval latency vs baseline (ms, log scale)")
    ax.set_ylabel("MRR")
    style(ax, "What each component costs vs what it buys")
    ax.text(0, 1.01, "bubble size = refusal recall  ·  retrieval time only, measured inside the generative runs",
            transform=ax.transAxes, fontsize=8.5, color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "cost-vs-gain.png", dpi=150)
    plt.close(fig)


def floor_overlap(rows: dict[str, dict]) -> None:
    scored = [r for r in rows.values() if r.get("top_score") is not None]
    ans = sorted(r["top_score"] for r in scored if r["cls"] != "should-refuse")
    ref = {r["id"]: r["top_score"] for r in scored if r["cls"] == "should-refuse"}
    lo, hi = min(ans), max(ref.values())  # lowest answerable .. highest should-refuse
    in_band = sum(lo <= r["top_score"] <= hi for r in scored)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axvspan(lo, hi, color="#f4d35e", alpha=0.25, label=f"overlap band: {in_band}/{len(scored)} questions ({in_band / len(scored):.0%})")
    ax.scatter(ans, [1] * len(ans), color=ANSWERABLE, alpha=0.6, s=40, label="answerable")
    ax.scatter(list(ref.values()), [0] * len(ref), color=REFUSE, alpha=0.7, s=40, label="should refuse")
    ax.axvline(FLOOR, color="black", linestyle="--", linewidth=1)
    ax.text(FLOOR, 1.3, f" floor {FLOOR}", fontsize=9)
    notes = (("refuse-gitlab-ci-pipeline", "GitLab CI {:.3f}\nabove {} answerable"),
             ("refuse-sourdough-bake", "sourdough (Docker Bake) {:.3f}\ncaught by the floor, barely"))
    for qid, label in notes:
        if qid in ref:
            above = sum(a < ref[qid] for a in ans)
            ax.annotate(label.format(ref[qid], above), (ref[qid], 0), xytext=(0, -30), textcoords="offset points",
                        ha="center", fontsize=8, arrowprops={"arrowstyle": "-", "alpha": 0.5})
    ax.set_yticks([0, 1], ["should refuse", "answerable"])
    ax.set_ylim(-1.0, 1.5)
    ax.set_xlabel("top-1 cosine similarity (dense retrieval, baseline run)")
    ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    style(ax, "Why a similarity floor can't be the classifier")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "floor-overlap.png", dpi=150)
    plt.close(fig)


def mrr_by_tag(runs: dict[str, dict], ids: list[str]) -> None:
    tags = ["exact-term", "paraphrase", "cross-source"]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    w = 0.26
    base = runs["baseline"]
    for i, (name, rows) in enumerate(runs.items()):
        vals, ns = [], []
        for t in tags:
            qs = [q for q in ids if base[q]["cls"] != "should-refuse" and t in base[q]["tags"]]
            vals.append(mean([rows[q]["reciprocal_rank"] or 0.0 for q in qs]))
            ns.append(len(qs))
        bars = ax.bar([k + (i - 1) * w for k in range(len(tags))], vals, w, label=name, color=COLORS[name])
        ax.bar_label(bars, fmt="%.2f", fontsize=8, padding=2)
    ax.set_xticks(range(len(tags)), [f"{t}\n(n={n})" for t, n in zip(tags, ns)])
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("MRR")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    style(ax, "MRR by question type: where each component helps")
    fig.tight_layout()
    fig.savefig(OUT / "mrr-by-tag.png", dpi=150)
    plt.close(fig)


def refusals(runs: dict[str, dict], ids: list[str]) -> None:
    parts = [
        ("correct refusal", "#4a3aa7", lambda r: r["cls"] == "should-refuse" and r["refused"]),
        ("answered a should-refuse (leak)", "#e34948", lambda r: r["cls"] == "should-refuse" and not r["refused"]),
        ("refused an answerable (false refusal)", "#1baf7a", lambda r: r["cls"] != "should-refuse" and r["refused"]),
    ]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    names = list(runs)
    left = [0] * len(names)
    for label, color, pred in parts:
        vals = [sum(pred(runs[n][q]) for q in ids) for n in names]
        bars = ax.barh(names, vals, left=left, color=color, label=label)
        ax.bar_label(bars, labels=[str(v) if v else "" for v in vals], label_type="center", color="white",
                     fontsize=9, fontweight="bold")
        left = [a + b for a, b in zip(left, vals)]
    ax.invert_yaxis()
    ax.set_xlabel("questions")
    ax.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=3)
    style(ax, "Refusal outcomes: the reranker leaks, hybrid doesn't")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "refusal-outcomes.png", dpi=150)
    plt.close(fig)


def rank_distribution(runs: dict[str, dict], ids: list[str]) -> None:
    buckets = [("rank 1", "#184f95", lambda r: r == 1), ("rank 2", "#3987e5", lambda r: r == 2),
               ("rank 3-5", "#9ec5f4", lambda r: r is not None and r >= 3), ("not in top 5", "#c9c8c0", lambda r: r is None)]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    names = list(runs)
    left = [0] * len(names)
    for label, color, pred in buckets:
        vals = [sum(pred(runs[n][q]["first_rank"]) for q in ids if runs[n][q]["cls"] != "should-refuse") for n in names]
        bars = ax.barh(names, vals, left=left, color=color, label=label, edgecolor="white", linewidth=2)
        ax.bar_label(bars, labels=[str(v) if v else "" for v in vals], label_type="center",
                     color="white" if color in ("#184f95", "#3987e5") else "#222", fontsize=9, fontweight="bold")
        left = [a + b for a, b in zip(left, vals)]
    ax.invert_yaxis()
    ax.set_xlabel("answerable questions")
    ax.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=4)
    style(ax, "Where the right document lands: more of it at rank 1")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "rank-distribution.png", dpi=150)
    plt.close(fig)


def floor_sweep(rows: dict[str, dict]) -> None:
    scored = [r for r in rows.values() if r.get("top_score") is not None]
    ans = [r["top_score"] for r in scored if r["cls"] != "should-refuse"]
    ref = [r["top_score"] for r in scored if r["cls"] == "should-refuse"]
    xs = [0.30 + i * 0.005 for i in range(121)]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(xs, [sum(s < x for s in ref) / len(ref) for x in xs], color=REFUSE, linewidth=2,
            label="traps refused by the floor alone (refusal recall)")
    ax.plot(xs, [sum(s < x for s in ans) / len(ans) for x in xs], color=ANSWERABLE, linewidth=2,
            label="good questions wrongly refused (false-refusal rate)")
    for x, label in ((0.35, "first guess 0.35:\nrefuses nothing"), (FLOOR, f"chosen {FLOOR}\n(rule, not tuned)"),
                     (0.73, "accuracy-max 0.73:\noverfits (75% held out)")):
        ax.axvline(x, color="#555", linestyle="--", linewidth=1)
        ax.text(x + 0.004, 0.84, label, fontsize=8, color="#333",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
    ax.set_xlim(0.30, 0.90)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("floor (top-1 cosine threshold)")
    ax.set_ylabel("share of questions")
    ax.legend(frameon=False, fontsize=8.5, loc="center left")
    style(ax, "Every floor that catches traps also refuses good questions")
    fig.tight_layout()
    fig.savefig(OUT / "floor-sweep.png", dpi=150)
    plt.close(fig)


def gates(runs: dict[str, dict], ids: list[str]) -> None:
    parts = [("gate 1: similarity floor", "#eb6834", "floor"), ("gate 2: citation check", "#2a78d6", "citation")]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    names = list(runs)
    left = [0] * len(names)
    for label, color, gate in parts:
        vals = [sum(runs[n][q]["refused"] and runs[n][q]["refused_by"] == gate for q in ids) for n in names]
        bars = ax.barh(names, vals, left=left, color=color, label=label, edgecolor="white", linewidth=2)
        ax.bar_label(bars, labels=[str(v) if v else "" for v in vals], label_type="center", color="white",
                     fontsize=9, fontweight="bold")
        left = [a + b for a, b in zip(left, vals)]
    ax.invert_yaxis()
    ax.set_xlabel("refusals (all questions)")
    ax.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=2)
    style(ax, "Which gate does the refusing: the citation check carries it")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "refusals-by-gate.png", dpi=150)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    loaded = {n: load(f) for n, f in RUNS.items()}
    digests = {h["question_set_sha256"] for h, _ in loaded.values()}
    if len(digests) != 1:
        raise SystemExit(f"question sets differ across runs: {digests}")
    runs = {n: rows for n, (_, rows) in loaded.items()}
    ids = [q for q in runs["baseline"] if all(q in r and not r[q].get("error") for r in runs.values())]
    headline(runs, ids)
    tradeoff(runs, ids)
    floor_overlap(runs["baseline"])
    mrr_by_tag(runs, ids)
    refusals(runs, ids)
    rank_distribution(runs, ids)
    floor_sweep(runs["baseline"])
    gates(runs, ids)
    for n, rows in runs.items():
        print(n, {k: round(v, 3) for k, v in metrics(rows, ids).items()},
              "retrieval p50 ms", round(statistics.median(rows[q]["retrieval_ms"] for q in ids), 1))
    print("wrote", *sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
