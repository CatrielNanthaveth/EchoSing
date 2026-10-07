# EchoSing Backend

FastAPI backend for EchoSing: song ingestion pipeline, catalog API and scoring engine.
See [../docs/BACKLOG.md](../docs/BACKLOG.md) for the roadmap.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)
- Docker Desktop (runs PostgreSQL and Redis)

## Setup

```bash
# From the repository root: start PostgreSQL (host port 5433) and Redis (6379)
docker compose up -d --wait

# From backend/
cp .env.example .env   # optional: defaults already match docker-compose.yml
uv sync

# From the repository root: install the git pre-commit hook (ruff, mypy, hygiene)
uv run --project backend pre-commit install
```

The hook runs automatically on `git commit`. To run it manually on every file:
`uv run --project backend pre-commit run --all-files`.

## Commands

Run from the `backend/` directory:

```bash
uv run uvicorn app.main:app --reload   # API at http://127.0.0.1:8000 (docs at /docs)
uv run pytest                          # unit tests (no Docker needed)
uv run pytest -m integration           # integration tests (needs docker compose up)
uv run ruff check .                    # lint
uv run ruff format .                   # format
uv run mypy app tests scripts          # type check (strict)
```

## ML stack (GPU machines only)

The ingestion pipeline (Demucs, Whisper, CREPE) lives in the optional `ml` dependency
group. It pins `torch==2.11.0+cu128`, the newest CUDA build with a matching
`torchaudio`, which supports Blackwell GPUs (`sm_120`, e.g. RTX 50xx).

```bash
# Prerequisite (Windows): winget install --id Gyan.FFmpeg -e
uv sync --group ml                     # ~3 GB of CUDA wheels
uv run python -m scripts.check_gpu     # verifies CUDA, sm_120, FFmpeg and ML imports
```

Note: a plain `uv sync` removes the `ml` group again; use `uv sync --group ml` on GPU
machines. `uv run` does not remove it.

`GET /health` returns 200 when PostgreSQL and Redis are reachable, 503 otherwise.

## Configuration

Settings are read from environment variables prefixed with `ECHOSING_` or from
`backend/.env`. See [.env.example](.env.example).
