"""Paired comparison of two eval runs — the table every phase row comes from.

    ./.venv/bin/python scripts/compare_runs.py eval/runs/baseline.jsonl eval/runs/+reranker.jsonl

Refuses to compare runs whose question sets differ, and compares only the questions that
completed without error in BOTH runs — so a question one arm failed on (rate limit, a
truncated reasoning trace) is excluded from both sides rather than silently scored as a
miss in one of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> tuple[dict, dict[str, dict]]:
    lines = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    header = next(l for l in lines if l.get("record") == "header")
    rows = {l["id"]: l for l in lines if "id" in l}
    return header, rows


def mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main(a_path: str, b_path: str) -> int:
    ha, a = load(a_path)
    hb, b = load(b_path)

    if ha["question_set_sha256"] != hb["question_set_sha256"]:
        print(f"REFUSED: question sets differ ({ha['question_set_sha256']} vs "
              f"{hb['question_set_sha256']}) — these runs are not comparable.")
        return 2

    diffs = [k for k in ("embedder", "chunk", "retrieval", "generator", "system_prompt_sha")
             if ha.get(k) != hb.get(k)]
    la, lb = ha.get("run_label", "A"), hb.get("run_label", "B")

    ok = [q for q in a if q in b and not a[q].get("error") and not b[q].get("error")]
    dropped = sorted(set(a) - set(ok))
    ans = [q for q in ok if a[q]["cls"] != "should-refuse"]
    ref = [q for q in ok if a[q]["cls"] == "should-refuse"]

    def metrics(r: dict[str, dict]) -> dict[str, float | None]:
        refused_ref = [bool(r[q].get("refused")) for q in ref]
        refused_ans = [bool(r[q].get("refused")) for q in ans]
        n_refusals = sum(refused_ref) + sum(refused_ans)
        return {
            "hit@5": mean([float(bool(r[q].get("hit"))) for q in ans]),
            "MRR": mean([r[q].get("reciprocal_rank") or 0.0 for q in ans]),
            "citation validity": mean([float(r[q]["citation_valid"]) for q in ans + ref
                                       if r[q].get("citation_valid") is not None]),
            "source accuracy": mean([float(r[q]["source_ok"]) for q in ans
                                     if r[q].get("source_ok") is not None]),
            "refusal recall": mean([float(x) for x in refused_ref]),
            "refusal precision": (sum(refused_ref) / n_refusals) if n_refusals else None,
            "false-refusal rate": mean([float(x) for x in refused_ans]),
            "p50 latency ms": sorted(r[q]["latency_ms"] for q in ok)[len(ok) // 2],
        }

    ma, mb = metrics(a), metrics(b)
    print(f"paired on {len(ok)} of {len(a)} questions  ({len(ans)} answerable, {len(ref)} should-refuse)")
    if dropped:
        print(f"excluded (errored in either run): {', '.join(dropped)}")
    print(f"config differences: {', '.join(diffs) or 'none'}")
    print()
    print(f"{'metric':<22}{la:>12}{lb:>12}{'delta':>10}")
    print("-" * 56)
    for k in ma:
        va, vb = ma[k], mb[k]
        if va is None or vb is None:
            print(f"{k:<22}{'-':>12}{'-':>12}")
            continue
        fmt = "{:>12.0f}" if "latency" in k else "{:>12.3f}"
        d = vb - va
        print(f"{k:<22}{fmt.format(va)}{fmt.format(vb)}{d:>+10.3f}" if "latency" not in k
              else f"{k:<22}{fmt.format(va)}{fmt.format(vb)}{d:>+10.0f}")

    moved = []
    for q in ok:
        ra, rb = bool(a[q].get("refused")), bool(b[q].get("refused"))
        if ra != rb:
            moved.append((q, a[q]["cls"], "refused" if ra else "answered", "refused" if rb else "answered"))
    if moved:
        print(f"\nverdict changed on {len(moved)} question(s):")
        for q, cls, x, y in moved:
            print(f"  {q:<38} {cls:<18} {x} -> {y}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
