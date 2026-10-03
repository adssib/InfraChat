"""A citation's link: the cited page, on GitHub, at the commit that was indexed.

The upstream docs move every day, so a link to `main` would drift away from what the
model actually read. Pinning to the indexed commit means the page a reader opens is the
page that was retrieved.

No line anchor, deliberately. A chunk's `source_location` counts lines in the *cleaned*
text — frontmatter and shortcodes already stripped (ingest/chunker.py) — so `L1-10` of a
chunk is not lines 1-10 of the file on GitHub; for workloads/pods/_index.md it is lines
13-22. A page link is right; a line link would be confidently wrong. The UI shows the
exact passage instead. Mapping chunks to raw-file lines is an ingest change (a new index
version) — docs/ROADMAP.md § Open.
"""

from __future__ import annotations

from infrachat.config import SourceConfig


def source_url(src: SourceConfig | None, doc: str) -> str | None:
    """`https://github.com/<repo>/blob/<commit>/<repo_path>/<doc>`, or None when the
    source doesn't say where it lives."""
    if src is None or not (src.repo and src.commit and src.repo_path):
        return None
    if not src.repo.startswith("https://github.com/"):
        return None
    return f"{src.repo.rstrip('/')}/blob/{src.commit}/{src.repo_path.strip('/')}/{doc}"
