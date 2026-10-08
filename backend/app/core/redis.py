"""Redis client factory and FastAPI dependency."""

from redis.asyncio import Redis
from starlette.requests import HTTPConnection


def create_redis_client(url: str) -> Redis:
    """Create an async Redis client.

    The client connects lazily, so creating it never fails even if Redis is
    unavailable.

    Args:
        url: Redis connection URL.

    Returns:
        A new async Redis client. The caller must close it with ``aclose()``.
    """
    client: Redis = Redis.from_url(url)
    return client


def get_redis(request: HTTPConnection) -> Redis:
    """Provide the application-wide Redis client.

    Args:
        request: Incoming request or WebSocket, used to reach the app state.

    Returns:
        The Redis client created during application startup.
    """
    client: Redis = request.app.state.redis
    return client
