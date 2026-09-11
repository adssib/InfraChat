"""Typed configuration — the only place untrusted input is parsed.

Two files, on purpose (docs/SPEC.md § Configuration model):

  sources.yaml   WHAT gets ingested. Stable, shared by every run.
  config.yaml    HOW this run behaves. One config = one eval run.

Splitting them means several experiment configs can share one corpus definition
without duplicating it — duplication there would silently break eval comparability.

Defaults follow one rule:

  Anything that changes the numbers is REQUIRED in YAML.
  Anything that turns a component off DEFAULTS to off.

A defaulted chunk size or floor could drift from the value a recorded run actually
used, invalidating the eval comparison with no error. A defaulted `rerank.enabled`
is the null object — it is what makes a commented-out block mean "disabled".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# A cleaning strategy per source: this is what makes a new doc format pluggable.
# Adding reStructuredText means a new value here and one Cleaner implementation —
# not a change to the ingestion pipeline.
CleanStrategy = Literal["plain", "hugo", "sphinx-rst"]


class SourceConfig(BaseModel):
    """One doc set. Defaults from sources.yaml are merged in before validation."""

    name: str                        # machine name, used in ids and citations
    label: str                       # human name, used in refusal text
    path: Path                       # root of the doc tree, relative to repo root
    include_ext: list[str]
    repo: str | None = None          # cloned by `ingest` when the path is missing
    clean: CleanStrategy = "plain"
    exclude_globs: list[str] = Field(default_factory=list)
    secret_patterns: list[str] = Field(default_factory=list)
    max_file_bytes: int = 100_000


class ChunkConfig(BaseModel):
    """Held fixed across every phase — so it must be stated, never inferred."""

    size: int
    overlap: int

    @model_validator(mode="after")
    def _overlap_fits(self) -> ChunkConfig:
        if self.overlap >= self.size:
            raise ValueError(f"chunk.overlap ({self.overlap}) must be < chunk.size ({self.size})")
        return self


class HybridConfig(BaseModel):
    enabled: bool = False
    fusion: Literal["rrf"] = "rrf"


class RetrievalConfig(BaseModel):
    retrieve_n: int
    k: int
    floor: float = Field(ge=0.0, le=1.0)   # required, but still range-checked
    hybrid: HybridConfig = Field(default_factory=HybridConfig)

    @model_validator(mode="after")
    def _k_fits(self) -> RetrievalConfig:
        if self.k > self.retrieve_n:
            raise ValueError(
                f"retrieval.k ({self.k}) must be <= retrieve_n ({self.retrieve_n}) — "
                "you cannot keep more chunks than you fetched"
            )
        return self


class RerankConfig(BaseModel):
    enabled: bool = False
    model: str = "Xenova/ms-marco-MiniLM-L-6-v2"


class RewriteConfig(BaseModel):
    enabled: bool = False
    model: str = ""


class EmbedderConfig(BaseModel):
    """Scores are not comparable across embedders, and `floor` is calibrated to one."""

    model: str


class LLMConfig(BaseModel):
    base_url: str
    model: str
    api_key_env: str = "INFRACHAT_LLM_API_KEY"
    max_context_chunks: int
    # Reasoning models (gpt-oss et al.) spend this budget on hidden reasoning tokens
    # BEFORE writing any answer. Too low and `content` comes back empty.
    max_tokens: int = 4096

    def api_key(self) -> str:
        """Read the key at call time, from the env var named in config.

        Never stored on the model, so it cannot leak into a repr, a log line, or a
        serialized config dump.
        """
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(
                f"${self.api_key_env} is not set. Export your API key:\n"
                f"    export {self.api_key_env}='...'"
            )
        return key


class EvalConfig(BaseModel):
    question_set: Path = Path("eval/questions.yaml")
    results_dir: Path = Path("eval/runs")
    run_label: str   # required: a defaulted label would overwrite the baseline results file


class CorpusConfig(BaseModel):
    sources_file: Path = Path("sources.yaml")


class Config(BaseModel):
    """The whole run configuration, with sources resolved and merged in."""

    data_dir: Path = Path("./data")
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    chunk: ChunkConfig
    embedder: EmbedderConfig
    retrieval: RetrievalConfig
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    rewrite: RewriteConfig = Field(default_factory=RewriteConfig)
    llm: LLMConfig | None = None   # commented out in config.yaml until build-step 5
    eval: EvalConfig

    sources: list[SourceConfig] = Field(default_factory=list)

    @property
    def db_path(self) -> Path:
        """The one SQLite file: chunks, manifest, vectors, and (Phase 3) FTS5."""
        return self.data_dir / "infrachat.db"

    @property
    def source_names(self) -> set[str]:
        """Valid values for `Chunk.source` — the open-string validation set."""
        return {s.name for s in self.sources}

    def source(self, name: str) -> SourceConfig:
        for s in self.sources:
            if s.name == name:
                return s
        raise KeyError(f"unknown source {name!r}; configured: {sorted(self.source_names)}")

    def require_llm(self) -> LLMConfig:
        """The generator config, or a message saying how to turn it on.

        Kept optional so the offline path and `ask --retrieval-only` run with no API
        key: a missing generator is a normal state in early Phase 1, not an error.
        """
        if self.llm is None:
            raise RuntimeError(
                "no generator configured — uncomment the `llm:` block in config.yaml "
                "(needed for `ask`; `ingest` and `ask --retrieval-only` do not use it)"
            )
        return self.llm

    def refusal_message(self) -> str:
        """Built from the configured labels, so adding a doc set updates it for free."""
        labels = [s.label for s in self.sources]
        if not labels:
            return "Not found in the configured docs."
        joined = labels[0] if len(labels) == 1 else " or ".join([", ".join(labels[:-1]), labels[-1]])
        return f"Not found in the {joined} docs."


def load_sources(path: Path) -> list[SourceConfig]:
    """Load sources.yaml, merging `defaults` under each source's own keys."""
    raw = yaml.safe_load(path.read_text()) or {}
    defaults = raw.get("defaults") or {}
    entries = raw.get("sources") or []
    if not entries:
        raise ValueError(f"{path}: no sources defined")

    sources = [SourceConfig(**{**defaults, **entry}) for entry in entries]

    names = [s.name for s in sources]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"{path}: duplicate source names {dupes}")
    return sources


def load_config(path: str | Path) -> Config:
    """Load config.yaml and the sources file it points at."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    if "infrachat" not in raw:
        raise ValueError(f"{path}: missing top-level 'infrachat:' key")

    cfg = Config(**raw["infrachat"])
    # sources_file is resolved relative to config.yaml, so the pair can move together
    cfg.sources = load_sources((path.parent / cfg.corpus.sources_file).resolve())
    return cfg
