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
uv run mypy app tests                  # type check (strict)
```

`GET /health` returns 200 when PostgreSQL and Redis are reachable, 503 otherwise.

## Configuration

Settings are read from environment variables prefixed with `ECHOSING_` or from
`backend/.env`. See [.env.example](.env.example).
