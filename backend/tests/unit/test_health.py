from fastapi import FastAPI
from httpx import AsyncClient

from app.schemas.health import HealthResponse
from app.services.health_service import HealthService, get_health_service


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert HealthResponse.model_validate(response.json()).status == "ok"


async def test_health_delegates_to_injected_service(
    app: FastAPI, client: AsyncClient
) -> None:
    calls: list[str] = []

    class SpyHealthService(HealthService):
        async def check(self) -> HealthResponse:
            calls.append("check")
            return await super().check()

    app.dependency_overrides[get_health_service] = SpyHealthService

    response = await client.get("/health")

    assert response.status_code == 200
    assert calls == ["check"]
