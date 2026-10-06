"""Health checks for the external dependencies of the service."""

from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DependencyCheck(Protocol):
    """A probe that verifies whether an external dependency is reachable."""

    @property
    def name(self) -> str:
        """Unique name of the dependency, used as key in the health report."""
        ...

    async def check(self) -> bool:
        """Probe the dependency.

        Returns:
            True if the dependency is healthy. Implementations may also raise
            on failure; callers treat exceptions as unhealthy.
        """
        ...


class PostgresCheck:
    """Checks that PostgreSQL accepts connections and runs queries."""

    name = "postgres"

    def __init__(self, engine: AsyncEngine) -> None:
        """Initialize the check.

        Args:
            engine: Engine used to open a connection.
        """
        self._engine = engine

    async def check(self) -> bool:
        """Run ``SELECT 1`` against the database.

        Returns:
            True if the query returned 1.
        """
        async with self._engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            value: int = result.scalar_one()
            return value == 1


class RedisCheck:
    """Checks that Redis answers a ``PING``."""

    name = "redis"

    def __init__(self, client: Redis) -> None:
        """Initialize the check.

        Args:
            client: Async Redis client to probe.
        """
        self._client = client

    async def check(self) -> bool:
        """Send ``PING`` to Redis.

        Returns:
            True if Redis replied to the ping.
        """
        return bool(await self._client.ping())
