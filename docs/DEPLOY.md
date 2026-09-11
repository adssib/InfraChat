# Deploying InfraChat

Two targets, one Dockerfile, and **one difference that drives everything else**: locally the
index is a mounted volume, on the public demo it is baked into the image.

| | Local / home-lab | Public demo (Hugging Face Spaces) |
|---|---|---|
| Stage | `--target app` | `demo` — the Dockerfile's **last** stage |
| `data/infrachat.db` | bind-mounted from `./data`, read-write | **copied into the image**, never mounted |
| `infrachat ingest` | **runs here.** This is where indexes are built | **never runs.** There is nothing to write to |
| Embedding model | baked in (`/opt/fastembed`) | baked in — plus `HF_HUB_OFFLINE=1` |
| Corpus (`./corpus`) | bind-mounted read-only | **absent.** The image ships the index built *from* it |
| `INFRACHAT_LLM_API_KEY` | compose `env_file: .env` | Space **repository secret** |

Free-tier Spaces have an **ephemeral filesystem**: anything written at runtime is gone on the
next restart, and there is no volume to mount. So the index is an *artifact* — built locally by
`ingest`, shipped inside the image, read-only in production. That is the whole deployment model
([ADR-0005](decisions/0005-one-sqlite-file.md), [ARCHITECTURE § Storage & packaging](ARCHITECTURE.md#storage--packaging)).

---

## Local

```bash
echo 'INFRACHAT_LLM_API_KEY=gsk_...' > .env      # gitignored; compose reads it, the image never does

docker compose build infrachat
docker compose run --rm infrachat ingest --dry-run -c config.yaml   # walk + chunk, no writes
docker compose run --rm infrachat ingest -c config.yaml            # build ./data/infrachat.db
docker compose run --rm infrachat ask --retrieval-only "what is a Pod?"   # no key needed
docker compose run --rm infrachat ask "how do I expose a Deployment?"     # needs the key
docker compose run --rm infrachat eval -c config.yaml              # writes ./eval/runs/*.jsonl
docker compose up infrachat                                        # the UI on :7860
```

- **The key never enters the image.** `config.yaml` names the env var (`llm.api_key_env`);
  compose injects the value from `.env` (gitignored, and excluded in `.dockerignore`). No
  `python-dotenv` anywhere — by the time the process starts this is an ordinary environment
  variable. `.env` is optional: `ingest` and `ask --retrieval-only` never read the key.
- **The container runs as uid 1000**, which is the normal desktop uid, so `./data` is writable
  through the mount with no `chown` dance.
- **`./data` must stay writable even for reads.** The store opens the database in WAL mode
  (`infrachat/store/chunks.py`), and WAL creates `-wal`/`-shm` files beside it. That is why the
  volume is not mounted `:ro`.
- `./corpus` *is* mounted `:ro` — `ingest` only ever reads it. `./eval` is mounted read-write,
  because eval run results are committed artifacts and belong on the host.

## The demo image

```bash
# 1. build the index locally first — the demo stage cannot be built without it
docker compose run --rm infrachat ingest -c config.yaml

# 2. build the image Spaces will build (last stage, no --target needed)
docker build --provenance=false --sbom=false -t infrachat:demo .

# 3. prove it behaves like the Space: no volume, no network, no API key
docker run --rm --network none infrachat:demo ask --retrieval-only "what is a Pod?"
#   → passed: top-1 0.834 vs floor 0.55 (margin +0.284)     [verified 2026-09-11]
```

Step 3 is the real test of this deployment model. `--network none` proves the image needs
neither HuggingFace (model pre-warmed into `/opt/fastembed` at build time) nor a volume
(index at `/app/data/infrachat.db`). If `data/infrachat.db` is missing, the build fails at the
`COPY` — deliberately: a demo image with no index answers nothing.

**Updating the demo = rebuilding the image.** There is no other path. Re-ingest locally, rebuild,
push.

## Hugging Face Spaces

Spaces with `sdk: docker` builds the repo's `Dockerfile` with **no `--target`**, so the final
stage is what gets deployed — hence `demo` is last. Do not reorder the stages.

**1. Add YAML frontmatter to `README.md`** — it must be the very first thing in the file, above
the `# InfraChat` heading. Spaces reads it as the Space card:

```yaml
---
title: InfraChat
emoji: 📘
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---
```

`sdk: docker` and `app_port: 7860` are the load-bearing lines. The image already matches:
`EXPOSE 7860`, plus `GRADIO_SERVER_NAME=0.0.0.0` and `GRADIO_SERVER_PORT=7860` so the UI binds
a reachable interface rather than localhost.

**2. Set the secret.** Space → *Settings* → *Variables and secrets* → **secret** named
`INFRACHAT_LLM_API_KEY`. A *variable* is visible in the Space UI and build logs; a *secret* is
not. Never bake it into the image, and never commit it.

**3. Push, including the index.** `data/` is gitignored in this repo, so the index has to be
force-added on the branch you push to the Space, and it is ~12MB — over HF's 10MB plain-git
threshold, so it needs LFS:

```bash
git remote add space https://huggingface.co/spaces/<user>/infrachat
echo 'data/infrachat.db filter=lfs diff=lfs merge=lfs -text' >> .gitattributes
git lfs install && git add .gitattributes
git add -f data/infrachat.db
git commit -m "demo: ship the pre-built index"
git push space HEAD:main
```

If LFS is a nuisance, the alternative is to host `infrachat.db` in a HF **Dataset** repo and
`RUN curl` it in the `demo` stage — same model (an artifact baked in at build time), different
transport.

**4. Cold start.** Nothing is downloaded at boot: model and index are both in the image. Expect
the usual Spaces container-start delay plus loading a 384-dim ONNX model, not a 65MB fetch.

---

## Image size — measured, not assumed

`docker history` on the `demo` image, **2026-09-11, linux/amd64**:

| Layer | Size |
|---|---|
| `python:3.12-slim` base (Debian trixie + CPython 3.12.14) | 142 MB |
| `/opt/venv` — all of `requirements.txt` | 467 MB |
| `/opt/fastembed` — pre-warmed `BAAI/bge-small-en-v1.5` ONNX | 67 MB |
| `data/infrachat.db` — 281 files · 4519 chunks · 4519 vectors | 13 MB |
| `infrachat/` + `config.yaml` + `sources.yaml` | 0.4 MB |
| **total** | **690 MB uncompressed · ~255 MB compressed (what a push transfers)** |

The `app` stage is the same minus the index: **677 MB**.

**No torch. Verified:**

```bash
docker run --rm --entrypoint sh infrachat:demo -c 'pip list | grep -iE "^(torch|tensorflow)"'
# → no output. fastembed runs the model through onnxruntime (ADR-0005).
```

The only `torch` hits in the image are dead filenames — `huggingface_hub/serialization/_torch.py`
and `onnxruntime/transformers/*`, optional conversion helpers that are never imported. A real
torch dependency would add 2–4 GB, which is the entire reason `fastembed` was chosen.

**Why 690 MB and not the ~300 MB quoted in ADR-0005.** That figure counts site-packages for the
*minimal* dependency set and nothing else. Three things are on top of it, and two are recent:

- +142 MB base image and +67 MB baked model — never counted in the 223 MB figure.
- +198 MB from `requirements.txt` being regenerated with `pip freeze` against the dev venv on
  2026-09-11: **gradio 83 MB** and its transitive **pandas 73 MB** (needed once `serve` lands),
  plus **pytest / pluggy / iniconfig**, which are test-only and have no business in a runtime
  image. Before that regeneration this image measured **492 MB**.

The lever, when size matters: split `requirements.txt` into runtime and dev sets. `pandas` is
pulled by gradio, not by InfraChat; `pillow` (21 MB) serves fastembed's image-embedding path,
which the text pipeline never touches; `pip` itself is 13 MB of the venv. None of that is a
Dockerfile change, so none of it was done here.

## Things worth knowing before you change the Dockerfile

- **`-slim`, not `-alpine`.** `onnxruntime` publishes manylinux wheels only; on musl, pip would
  fall back to compiling it. The builder passes `--only-binary=:all:` as a tripwire: if any
  dependency ever wants to build from source, the build stops instead of quietly needing a
  compiler.
- **Loadable SQLite extensions work in `python:3.12-slim`** — the constraint ADR-0005 flags as
  "some distro-built Pythons disable it". Verified in the image:
  `sqlite-vec v0.1.9 | sqlite 3.46.1`.
- **The embedder name is read from `config.yaml` at build time**, not repeated in the
  Dockerfile. The embedder is one of the four things held fixed across phases
  ([CLAUDE.md](../CLAUDE.md)); two copies of its name would be two places to drift.
- **`ENTRYPOINT` is `python -m infrachat`**, so the container's command *is* the subcommand:
  `docker run infrachat:demo ask --retrieval-only "..."`.

## Known gaps

- **`serve` is not wired yet.** `CMD` already points at it; today `docker compose up` prints
  `infrachat serve is not built yet` and exits 2. The Dockerfile needs no change when the UI
  lands — gradio is already in the image.
- **`eval` is not built yet either**, and like `ingest` it is a *local* job, not something the
  demo image does. So nothing under `eval/` is baked in: the local service mounts `./eval`
  read-write instead, which puts the question set in and leaves `eval/runs/*.jsonl` — the
  committed output — on the host. `.dockerignore` keeps `eval/runs/` out of the build context.
- **Nothing here has been run on Spaces.** Everything above was verified locally, including the
  no-volume/no-network demo path; the Spaces-specific claims (frontmatter keys, `app_port`, uid
  1000, the 10MB LFS threshold, secret injection) come from HF's documented behaviour and should
  be confirmed on the first real deploy.
