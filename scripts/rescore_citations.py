"""Re-derive citation fields from stored answers — no LLM calls.

    ./.venv/bin/python scripts/rescore_citations.py eval/runs/baseline.jsonl [more.jsonl ...]

Citation validity is computed from `answer_text` and the retrieved chunks, both of which
every row stores. So when the citation parser is fixed, a run can be re-scored for free
instead of re-generated. First used after `parse_tag_candidates` was found to read image
tags inside HCL code blocks (`myapp:release`) as invented citations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrachat.answer.citations import parse_tag_candidates  # noqa: E402
from infrachat.models import cite_tag  # noqa: E402


def rescore(path: Path) -> tuple[int, int]:
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    header = next(l for l in lines if l.get("record") == "header")
    max_chunks = (header.get("generator") or {}).get("max_context_chunks")
    changed = scored = 0
    for row in lines:
        if "id" not in row or row.get("error") or row.get("refused") or not row.get("answer_text"):
            continue
        hits = row.get("retrieved") or []
        offered = {cite_tag(h["source"], h["doc"]) for h in (hits[:max_chunks] if max_chunks else hits)}
        cited = parse_tag_candidates(row["answer_text"])
        invalid = [t for t in cited if t not in offered]
        valid = bool(cited) and not invalid
        scored += 1
        if (cited, invalid, valid) != (row.get("cited_tags"), row.get("invalid_tags"), row.get("citation_valid")):
            changed += 1
        row["cited_tags"], row["invalid_tags"], row["citation_valid"] = cited, invalid, valid
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    return scored, changed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    for arg in sys.argv[1:]:
        scored, changed = rescore(Path(arg))
        print(f"{arg}: re-scored {scored} answers, {changed} changed")
