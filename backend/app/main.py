"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import health


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        The configured application with all routers registered.
    """
    application = FastAPI(title="EchoSing API", version="0.1.0")
    application.include_router(health.router)
    return application


app = create_app()
