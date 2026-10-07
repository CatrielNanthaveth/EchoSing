import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def analysis_json() -> dict[str, Any]:
    """Synthetic, valid analysis (3 lines, 300 frames) as stored in the database."""
    data: dict[str, Any] = json.loads(
        (FIXTURES_DIR / "analysis_v1.json").read_text("utf-8")
    )
    return data


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, health_check_timeout_s=0.5)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client that does NOT run the app lifespan (no real infrastructure)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
