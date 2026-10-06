# EchoSing Backend

FastAPI backend for EchoSing: song ingestion pipeline, catalog API and scoring engine.
See [../docs/BACKLOG.md](../docs/BACKLOG.md) for the roadmap.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)

## Commands

Run from the `backend/` directory:

```bash
uv sync                          # install dependencies
uv run uvicorn app.main:app --reload   # start the API at http://127.0.0.1:8000
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy app tests            # type check (strict)
```
