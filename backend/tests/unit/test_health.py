import asyncio

from fastapi import FastAPI
from httpx import AsyncClient

from app.services.health_service import HealthService, get_health_service


class FakeCheck:
    def __init__(
        self,
        name: str,
        *,
        healthy: bool = True,
        error: bool = False,
        hang: bool = False,
    ) -> None:
        self.name = name
        self._healthy = healthy
        self._error = error
        self._hang = hang

    async def check(self) -> bool:
        if self._hang:
            await asyncio.sleep(10)
        if self._error:
            raise ConnectionError("boom")
        return self._healthy


def make_service(*checks: FakeCheck) -> HealthService:
    return HealthService(checks=checks, timeout_s=0.05)


async def test_all_checks_up_reports_ok() -> None:
    result = await make_service(FakeCheck("postgres"), FakeCheck("redis")).check()

    assert result.status == "ok"
    assert result.checks == {"postgres": "up", "redis": "up"}


async def test_unhealthy_check_reports_degraded() -> None:
    service = make_service(FakeCheck("postgres"), FakeCheck("redis", healthy=False))

    result = await service.check()

    assert result.status == "degraded"
    assert result.checks == {"postgres": "up", "redis": "down"}


async def test_raising_check_is_down() -> None:
    result = await make_service(FakeCheck("postgres", error=True)).check()

    assert result.status == "degraded"
    assert result.checks == {"postgres": "down"}


async def test_hanging_check_times_out_as_down() -> None:
    result = await make_service(FakeCheck("redis", hang=True)).check()

    assert result.checks == {"redis": "down"}


async def test_no_checks_reports_ok() -> None:
    result = await make_service().check()

    assert result.status == "ok"
    assert result.checks == {}


async def test_endpoint_returns_200_when_ok(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: make_service(
        FakeCheck("postgres")
    )

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "up"}}


async def test_endpoint_returns_503_when_degraded(
    app: FastAPI, client: AsyncClient
) -> None:
    app.dependency_overrides[get_health_service] = lambda: make_service(
        FakeCheck("postgres"), FakeCheck("redis", error=True)
    )

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"postgres": "up", "redis": "down"},
    }
