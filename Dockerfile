# syntax=docker/dockerfile:1
#
# InfraChat — one Dockerfile, two runtime stages that do genuinely different jobs.
#
#   docker build --target app .   local / home-lab. No index inside the image: ./data is a
#                                 mounted volume and `ingest` writes into it.
#   docker build .                the public demo (stage `demo`). The pre-built index is
#                                 COPIED INTO the image, no volume is ever mounted, and
#                                 `infrachat ingest` never runs there.
#
# `demo` is the LAST stage on purpose: Hugging Face Spaces builds the Dockerfile with no
# `--target`, so whatever ends up last is what the public demo gets. Do not reorder.
#
# Base is `-slim` (glibc), not `-alpine` (musl): onnxruntime publishes manylinux wheels
# only, so on Alpine pip would fall back to compiling it. See docs/DEPLOY.md.

ARG PYTHON_VERSION=3.12

# --------------------------------------------------------------------------- builder
# Wheels and the ONNX model are assembled here. The runtime stages copy the two results
# (/opt/venv, /opt/fastembed) and inherit none of the build tooling.
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Pinned, and deliberately torch-free — see the header comment in requirements.txt.
# `--only-binary=:all:` is a tripwire, not an optimisation: every dependency here has a
# manylinux wheel, so if pip ever wants to build from source the build stops instead of
# quietly needing a compiler (and, for a torch-shaped dependency, gigabytes).
COPY requirements.txt ./
RUN pip install --only-binary=:all: --requirement requirements.txt

# Bake the embedding model into the image. The demo has an ephemeral filesystem and no
# volume, so a model fetched at boot is re-fetched on every cold start and the first
# question pays for it. The model NAME is read from config.yaml rather than repeated
# here — the embedder is one of the four things held fixed across phases (CLAUDE.md).
COPY config.yaml ./
RUN python <<'PY'
import yaml
from fastembed import TextEmbedding

model = yaml.safe_load(open("config.yaml"))["infrachat"]["embedder"]["model"]
print(f"pre-warming {model} into $FASTEMBED_CACHE_PATH", flush=True)
vector = next(iter(TextEmbedding(model).query_embed(["build-time smoke test"])))
print(f"ok: {model} -> {len(vector)} dims", flush=True)
PY

# --------------------------------------------------------------------------- base
# Everything both runtime stages share. Nothing here knows whether an index exists.
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HOME=/home/app \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

# uid 1000 deliberately: Spaces runs containers as uid 1000, and locally it is the
# desktop user's uid, so the mounted ./data is writable with no chown dance.
RUN useradd --create-home --uid 1000 app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=app:app /opt/fastembed /opt/fastembed

WORKDIR /app
# The package is not pip-installed; `python -m infrachat` finds it because /app is the
# working directory. config.yaml + sources.yaml are the only configuration the runtime
# reads, and the corpus they point at is mounted, never copied.
COPY --chown=app:app infrachat/ ./infrachat/
COPY --chown=app:app config.yaml sources.yaml ./

# The one SQLite file lives here (ADR-0005). This directory must stay writable even when
# the index is logically read-only: the store opens the database in WAL mode
# (infrachat/store/chunks.py), and WAL creates `-wal`/`-shm` files next to it.
RUN install --directory --owner=app --group=app /app/data

# Gradio on 7860 — the port Hugging Face Spaces expects (docs/DEPLOY.md).
EXPOSE 7860

# Subcommands map onto the container's command: ingest | ask | eval | serve.
#   docker run --rm infrachat:local ask --retrieval-only "what is a Pod?"
ENTRYPOINT ["python", "-m", "infrachat"]
# `serve` is not wired yet — today this exits 2 with an honest message instead of a
# traceback, and when the UI lands this line already points at it.
CMD ["serve", "-c", "config.yaml"]

# --------------------------------------------------------------------------- app
# Local / home-lab. No index in the image: docker-compose mounts ./data here read-write
# and ./corpus read-only. This is the only stage in which `ingest` ever runs.
FROM base AS app
USER app

# --------------------------------------------------------------------------- demo
# The public demo. LAST stage = what Spaces builds by default.
FROM base AS demo

# The index ships INSIDE the image, as a build artifact. Free-tier Spaces filesystems are
# ephemeral, so there is no volume that would survive a restart and nothing to ingest
# into. Build this first, locally:
#     docker compose run --rm infrachat ingest -c config.yaml
# If data/infrachat.db is missing the build fails here — loudly, which is the point: a
# demo image with no index is a demo that answers nothing.
COPY --chown=app:app data/infrachat.db /app/data/infrachat.db

# Proof rather than hope: the weights are already in /opt/fastembed, so the demo must
# never reach HuggingFace at runtime. If the pre-warm ever drifts from config.yaml,
# fastembed fails instead of silently downloading ~65MB on a visitor's first question.
ENV HF_HUB_OFFLINE=1

USER app
