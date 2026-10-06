"""Tests against the real services from docker-compose.yml.

Run with: ``docker compose up -d`` and then ``uv run pytest -m integration``.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.requests import Request

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app

pytestmark = pytest.mark.integration


async def _client_with_lifespan(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def live_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for ac in _client_with_lifespan(app):
        yield ac


async def test_health_reports_all_dependencies_up(live_client: AsyncClient) -> None:
    response = await live_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"postgres": "up", "redis": "up"},
    }


async def test_health_reports_unreachable_redis_as_down(settings: Settings) -> None:
    broken = settings.model_copy(update={"redis_url": "redis://localhost:6390/0"})

    async for ac in _client_with_lifespan(create_app(broken)):
        response = await ac.get("/health")

    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "up", "redis": "down"}


async def test_db_session_dependency_runs_queries(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        request = Request({"type": "http", "app": app})
        async for session in get_db_session(request):
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
