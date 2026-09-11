"""F2 — corpus filter matching, in both directions.

Why this file exists: both failure modes here are silent.

  A pattern that UNDER-matches embeds a credential file. Nothing errors, nothing is
  logged, and the text is retrievable from then on.
  A pattern that OVER-matches deletes real documentation. This already happened:
  `*secret*` excluded the Kubernetes Secrets docs — the index just quietly lacked a
  topic, and retrieval looked "bad" instead of broken.

The patterns under test are the REAL ones from `sources.yaml`, not a copy, because the
bug lives in the pattern list rather than in `judge()`.
"""

from pathlib import Path

import pytest

from infrachat.config import load_sources
from infrachat.ingest.filter import DropReason, judge
from infrachat.ingest.loader import CandidateFile

SOURCES = {s.name: s for s in load_sources(Path(__file__).resolve().parents[1] / "sources.yaml")}


def candidate(source: str, rel_path: str, size: int = 2_000) -> CandidateFile:
    return CandidateFile(source=source, path=Path("/corpus") / rel_path, rel_path=rel_path, size=size)


@pytest.mark.parametrize(
    "rel_path",
    [
        ".env",
        ".env.production",
        "credentials",                       # a directory, caught as a path segment
        "credentials.json",
        "deploy/credentials/kubeconfig.yaml",
        "tls/server.key",
        "certs/ca.pem",
        "clusters/prod.pfx",
        "id_rsa",
        "id_rsa.pub",
        ".htpasswd",
    ],
)
def test_credential_file_is_dropped_before_anything_can_embed_it(rel_path: str) -> None:
    verdict = judge(candidate("kubernetes", rel_path), SOURCES["kubernetes"])
    assert verdict.reason is DropReason.SECRET, (
        f"{rel_path!r} was not matched by any secret pattern — it would be embedded, "
        "and text in the index cannot be un-embedded"
    )


@pytest.mark.parametrize(
    ("source", "rel_path"),
    [
        ("kubernetes", "configuration/secret.md"),
        ("kubernetes", "security/secrets-good-practices.md"),
        ("docker", "building/secrets.md"),
        ("docker", "ci/github-actions/secrets.md"),
    ],
)
def test_secrets_documentation_is_not_silently_deleted_by_a_secret_pattern(
    source: str, rel_path: str
) -> None:
    # These four paths exist in the corpus. A word-matching pattern such as `*secret*`
    # drops all of them, and the only symptom is an index that cannot answer about Secrets.
    verdict = judge(candidate(source, rel_path), SOURCES[source])
    assert verdict.kept, (
        f"{rel_path!r} dropped by {verdict.reason} ({verdict.pattern!r}) — "
        "that is real documentation, not a credential"
    )


@pytest.mark.parametrize("rel_path", ["_print/index.md", "workloads/_print/index.md"])
def test_print_duplicates_are_excluded_at_the_source_root_too(rel_path: str) -> None:
    # `**/_print/**` only matches a nested path under plain fnmatch; a `_print/` tree
    # sitting at the source root would slip through and index every page twice.
    verdict = judge(candidate("kubernetes", rel_path), SOURCES["kubernetes"])
    assert verdict.reason is DropReason.EXCLUDED, f"{rel_path!r} would be indexed as a duplicate"
