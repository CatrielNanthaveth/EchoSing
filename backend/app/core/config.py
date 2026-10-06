"""Application settings loaded from environment variables and ``.env``."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    Every field can be overridden with an environment variable prefixed with
    ``ECHOSING_`` (e.g. ``ECHOSING_DATABASE_URL``) or in a ``.env`` file located
    in the working directory.

    Attributes:
        database_url: SQLAlchemy async URL of the PostgreSQL database.
        redis_url: URL of the Redis server.
        health_check_timeout_s: Max seconds a single dependency check may take.
    """

    model_config = SettingsConfigDict(
        env_prefix="ECHOSING_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://echosing:echosing@localhost:5433/echosing"
    redis_url: str = "redis://localhost:6379/0"
    health_check_timeout_s: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Returns:
        The cached ``Settings`` object.
    """
    return Settings()
