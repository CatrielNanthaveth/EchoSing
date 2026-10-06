"""Service that reports the health of the application and its dependencies."""

import asyncio
import logging
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.db.session import get_engine
from app.schemas.health import CheckStatus, HealthResponse
from app.services.health_checks import DependencyCheck, PostgresCheck, RedisCheck

logger = logging.getLogger(__name__)


class HealthService:
    """Aggregates dependency checks into a single health report."""

    def __init__(self, checks: Sequence[DependencyCheck], timeout_s: float) -> None:
        """Initialize the service.

        Args:
            checks: Dependency probes to run on every health check.
            timeout_s: Max seconds each probe may take before counting as down.
        """
        self._checks = checks
        self._timeout_s = timeout_s

    async def check(self) -> HealthResponse:
        """Run all dependency checks concurrently.

        Returns:
            ``"ok"`` if every dependency is up, ``"degraded"`` otherwise, along
            with the status of each dependency.
        """
        statuses = await asyncio.gather(*(self._run(c) for c in self._checks))
        checks = {c.name: s for c, s in zip(self._checks, statuses, strict=True)}
        overall = "ok" if all(s == "up" for s in statuses) else "degraded"
        return HealthResponse(status=overall, checks=checks)

    async def _run(self, check: DependencyCheck) -> CheckStatus:
        """Run a single check, converting failures and timeouts to ``"down"``."""
        try:
            async with asyncio.timeout(self._timeout_s):
                healthy = await check.check()
        except Exception:
            logger.warning("Health check %r failed", check.name, exc_info=True)
            return "down"
        return "up" if healthy else "down"


def get_health_service(
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthService:
    """Provide a ``HealthService`` wired to the real dependencies.

    Args:
        engine: Application database engine.
        redis: Application Redis client.
        settings: Application settings.

    Returns:
        A ``HealthService`` checking PostgreSQL and Redis.
    """
    return HealthService(
        checks=[PostgresCheck(engine), RedisCheck(redis)],
        timeout_s=settings.health_check_timeout_s,
    )
