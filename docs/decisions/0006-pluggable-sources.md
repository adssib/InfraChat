# ADR-0006: A doc set is a YAML entry, not a code change

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1

## Context

The project is framed around pluggability, but that word was only ever applied to *retrieval
components* — reranker, hybrid, rewriter. The corpus was fixed: `docs/SPEC.md` listed
"Doc sets beyond Kubernetes + Docker" under **Out of scope**.

That is the wrong boundary. Adding Ansible, Terraform, or Helm docs is the most obvious way this
project grows, and three things stood in the way — none of them fundamental:

1. **A closed `Source` enum** (`KUBERNETES | DOCKER`) — adding a doc set meant editing code.
2. **A hardcoded refusal message** — *"Not found in the Kubernetes or Docker docs."*
3. **Markup is per-source.** Kubernetes and Docker docs are Hugo markdown; **Ansible's are
   reStructuredText**. A chunker that assumes one format cannot ingest the other.

## Decision

**The corpus is declared in `sources.yaml`, and adding a source is a YAML entry.**

- `Source` is an **open string**, validated at config load against the configured source names —
  not an enum.
- Each source declares a **`clean:` strategy** (`plain | hugo | sphinx-rst`). This is the format
  seam: supporting RST means one new Cleaner implementation, never a pipeline change.
- The **refusal message is generated** from the configured `label:` fields, so a new doc set
  updates it for free.
- `sources.yaml` is **separate from `config.yaml`** because several experiment configs share one
  corpus definition; duplicating the corpus block per config would silently break comparability.

## Alternatives considered

- **Keep the enum, add members as needed.** Type-safe and self-documenting, but every doc set is
  a code change plus a release — the opposite of the stated goal.
- **One loader implementation per source.** Maximum flexibility per source, but the shared 95%
  (walk, filter, chunk, embed) gets copied, and the copies drift.
- **Put sources inside `config.yaml`.** One less file, but the corpus definition would be
  duplicated across every experiment config, and a divergence between two of them would silently
  invalidate an eval comparison.

## Consequences

- ✅ **Adding a doc set is four lines of YAML** — `sources.yaml` carries a commented Ansible entry
  as the worked example.
- ✅ **The refusal message, citations, and eval classes all follow the config** rather than being
  restated in code.
- ✅ **New markup formats are a Cleaner implementation**, the same null-object pattern as the
  retrieval seams ([ADR-0002](0002-null-object-seams.md)).
- ⚠️ **An open string has no static safety.** `source="kubernetse"` is a typo the type system
  cannot catch; validation happens at config load, and only there.
- ⚠️ **Adding a source invalidates every prior eval run.** It changes the corpus, and it can flip
  a `should-refuse` question into an answerable one ("how do I write an Ansible playbook?").
  Source additions are therefore **orthogonal to the build phases**: extend the question set,
  re-run the baseline, start a new comparison table. This is the consequence most likely to be
  forgotten, so it is stated in `sources.yaml` itself.
- ⚠️ **Not every doc set will fit.** A source whose docs are generated HTML, or whose markup no
  Cleaner handles, needs real work — pluggable is not free.
- 🔭 Revisit if a source needs per-source chunking as well as per-source cleaning; that would mean
  the chunker needs a seam too.
