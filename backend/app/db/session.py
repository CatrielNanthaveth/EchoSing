"""Database engine, session factory and FastAPI dependencies."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    """Create the async SQLAlchemy engine.

    The engine connects lazily, so creating it never fails even if the
    database is unavailable.

    Args:
        url: SQLAlchemy async database URL.

    Returns:
        A new engine. The caller must release it with ``dispose()``.
    """
    return create_async_engine(url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine.

    Args:
        engine: Engine the sessions will use.

    Returns:
        A factory producing ``AsyncSession`` objects.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


def get_engine(request: Request) -> AsyncEngine:
    """Provide the application-wide database engine.

    Args:
        request: Incoming request, used to reach the application state.

    Returns:
        The engine created during application startup.
    """
    engine: AsyncEngine = request.app.state.engine
    return engine


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a database session scoped to a single request.

    Args:
        request: Incoming request, used to reach the application state.

    Yields:
        An ``AsyncSession`` that is closed when the request finishes.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
