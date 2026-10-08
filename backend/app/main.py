"""FastAPI application entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

from app.api.routes import admin, health, songs
from app.core.config import Settings, get_settings
from app.core.redis import create_redis_client
from app.db.session import create_engine, create_session_factory
from app.services.song_ingestion import AUDIO_CONTENT_TYPES

AUDIO_MEDIA_TYPES = tuple(sorted(set(AUDIO_CONTENT_TYPES.values())))


def _build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the lifespan handler that owns the shared infrastructure clients.

    Args:
        settings: Settings used to configure the clients.

    Returns:
        A lifespan context manager factory for ``FastAPI``.
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        redis = create_redis_client(settings.redis_url)
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        application.state.redis = redis
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Settings to use. Defaults to the process-wide settings.

    Returns:
        The configured application with all routers registered.
    """
    resolved = settings or get_settings()
    application = FastAPI(
        title="EchoSing API",
        version="0.1.0",
        lifespan=_build_lifespan(resolved),
    )
    application.dependency_overrides[get_settings] = lambda: resolved
    # Lyrics and pitch curves are large, highly compressible JSON documents.
    # Audio is already compressed, and gzipping it would break range requests.
    application.add_middleware(
        GZipMiddleware,
        minimum_size=1000,
        exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, *AUDIO_MEDIA_TYPES),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
        # Needed by audio players doing range requests from another origin.
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"],
    )
    application.include_router(health.router)
    application.include_router(songs.router)
    application.include_router(admin.router)
    return application


app = create_app()
