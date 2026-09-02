"""F4 — the Embedder seam: text → vectors.

`fastembed` runs the model through ONNX, so there is **no torch** in the dependency tree
(ADR-0005): ~220MB of packages instead of multiple gigabytes, which is what keeps the
demo image small and its cold start survivable.

**The asymmetry is the thing to get right.** `bge-small-en-v1.5` is trained so that a
query and a passage are encoded differently — the query gets an instruction prefix. Using
the passage encoder for queries does not error; it just quietly returns worse neighbours.
Hence two methods rather than one `embed()`.
"""

from __future__ import annotations

from typing import Iterable, Protocol, Sequence


class Embedder(Protocol):
    """The seam. Any implementation must keep documents and queries distinct."""

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Default implementation — local CPU, ONNX, no network after the first run.

    The model is loaded lazily: importing this module must not download 100MB, so that
    `--dry-run` and `--help` stay instant and offline.
    """

    def __init__(self, model_name: str, *, batch_size: int = 64) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
        self._dim: int | None = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # imported here, not at module level

            self._model = TextEmbedding(self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        """Vector width — the store needs it to declare the vec0 column."""
        if self._dim is None:
            from fastembed import TextEmbedding

            for spec in TextEmbedding.list_supported_models():
                if spec["model"] == self.model_name:
                    self._dim = int(spec["dim"])
                    break
            else:  # unknown model: probe it once
                self._dim = len(self.embed_query("dimension probe"))
        return self._dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode chunks for storage. Vectors come back unit-normalised."""
        model = self._load()
        return [v.tolist() for v in model.passage_embed(list(texts), batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        """Encode a question. **Not** the same encoder as `embed_documents`."""
        model = self._load()
        return next(iter(model.query_embed([text]))).tolist()


def build(model_name: str) -> Embedder:
    """Construct the configured embedder — the one place the implementation is named."""
    return FastEmbedEmbedder(model_name)
