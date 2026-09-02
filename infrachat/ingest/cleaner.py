"""F3 (first half) — strip a source's markup before chunking.

The per-source format seam (ADR-0006). `sources.yaml` names a strategy per source;
supporting a new doc format means one implementation here, never a pipeline change.

Why this is not just `re.sub(r"\\{\\{<.*?>\\}\\}", "", text)`: the corpus has 2,463 Hugo
shortcodes across 28 names, and they do not all mean the same thing.

    {{< note >}} ... {{< /note >}}                  a WRAPPER — the prose inside is real
    {{< glossary_tooltip text="cluster" ... >}}     the visible word is inside the tag
    {{< feature-state ... >}} · {{% code_sample %}} metadata / external refs — no prose

Nuking every shortcode would delete 561 glossary terms — "cluster", "Pod", "Deployment" —
which are precisely the words a retrieval query matches on.
"""

from __future__ import annotations

import re
from typing import Protocol

# ---- shared: YAML frontmatter -------------------------------------------------
# All 281 files in the current corpus open with it, so this is universal, not optional.
_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)

# ---- Hugo ---------------------------------------------------------------------
# A shortcode carrying visible text: keep the text, drop the tag.
_TEXT_ATTR = re.compile(r"\{\{[<%]\s*\w[\w-]*[^}]*?\btext=\"([^\"]*)\"[^}]*?[>%]\}\}")
# Everything else, opening or closing, `{{< >}}` or `{{% %}}`.
_SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
# Three or more newlines collapse to a paragraph break.
_BLANK_RUN = re.compile(r"\n{3,}")


class Cleaner(Protocol):
    """Raw file text → text worth embedding."""

    def clean(self, text: str) -> str: ...


def strip_frontmatter(text: str) -> str:
    """Remove a leading `---` YAML block. A no-op when there isn't one."""
    return _FRONTMATTER.sub("", text, count=1)


def _tidy(text: str) -> str:
    return _BLANK_RUN.sub("\n\n", text).strip() + "\n"


class PlainCleaner:
    """Frontmatter only. The right choice for a source with no template markup."""

    name = "plain"

    def clean(self, text: str) -> str:
        return _tidy(strip_frontmatter(text))


class HugoCleaner:
    """Frontmatter plus Hugo shortcodes, in the order that preserves prose.

    Order matters: text-carrying shortcodes are unwrapped *before* the blanket removal,
    or their content goes with the tag. Wrapper shortcodes need no special case — their
    prose sits *between* the tags, so removing the tags leaves it behind.
    """

    name = "hugo"

    def clean(self, text: str) -> str:
        text = strip_frontmatter(text)
        text = _TEXT_ATTR.sub(r"\1", text)   # {{< glossary_tooltip text="cluster" >}} -> cluster
        text = _SHORTCODE.sub("", text)      # wrappers, metadata, external refs
        return _tidy(text)


class SphinxRstCleaner:
    """Placeholder for reStructuredText sources (Ansible et al.).

    Declared so `clean: sphinx-rst` validates and the seam is visible, but deliberately
    not implemented: writing an RST stripper against no RST corpus would be guesswork.
    It lands with the first RST source.
    """

    name = "sphinx-rst"

    def clean(self, text: str) -> str:
        raise NotImplementedError(
            "the sphinx-rst cleaner is not implemented yet — it lands with the first "
            "reStructuredText source. Use clean: plain to ingest without stripping."
        )


_CLEANERS: dict[str, Cleaner] = {
    c.name: c() for c in (PlainCleaner, HugoCleaner, SphinxRstCleaner)
}


def for_strategy(strategy: str) -> Cleaner:
    """Look up the cleaner named by a source's `clean:` key."""
    try:
        return _CLEANERS[strategy]
    except KeyError:
        raise ValueError(
            f"unknown clean strategy {strategy!r}; known: {sorted(_CLEANERS)}"
        ) from None
