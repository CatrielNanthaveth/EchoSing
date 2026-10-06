"""Redis client factory and FastAPI dependency."""

from fastapi import Request
from redis.asyncio import Redis


def create_redis_client(url: str) -> Redis:
    """Create an async Redis client.

    The client connects lazily, so creating it never fails even if Redis is
    unavailable.

    Args:
        url: Redis connection URL.

    Returns:
        A new async Redis client. The caller must close it with ``aclose()``.
    """
    return Redis.from_url(url)


def get_redis(request: Request) -> Redis:
    """Provide the application-wide Redis client.

    Args:
        request: Incoming request, used to reach the application state.

    Returns:
        The Redis client created during application startup.
    """
    client: Redis = request.app.state.redis
    return client
