"""Application settings loaded from environment variables and ``.env``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import SeparationPreset


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    Every field can be overridden with an environment variable prefixed with
    ``ECHOSING_`` (e.g. ``ECHOSING_DATABASE_URL``) or in a ``.env`` file located
    in the working directory.

    Attributes:
        database_url: SQLAlchemy async URL of the PostgreSQL database.
        redis_url: URL of the Redis server.
        health_check_timeout_s: Max seconds a single dependency check may take.
        storage_root: Directory where ``LocalStorage`` keeps audio files.
        admin_token: Shared secret required in ``X-Admin-Token`` by admin
            endpoints. When unset, admin endpoints are disabled.
        max_upload_bytes: Max size of an uploaded song file.
        ml_device: Torch device for ML models (``cuda`` or ``cpu``).
        ml_models_dir: Where downloaded model weights are cached.
        default_separation_preset: Preset used when a song does not choose one.
        separation_timeout_s: Max seconds one source separation may take.
        demucs_model: Demucs model of the ``demucs`` preset.
        demucs_shifts: Demucs random shifts averaged per song; higher values
            reduce artifacts at a linear cost in time.
        roformer_model: audio-separator model file of the ``roformer`` preset.
        roformer_normalization: Peak amplitude audio-separator normalizes the
            input and output to.
    """

    model_config = SettingsConfigDict(
        env_prefix="ECHOSING_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://echosing:echosing@localhost:5433/echosing"
    redis_url: str = "redis://localhost:6379/0"
    health_check_timeout_s: float = 2.0
    storage_root: Path = Path("storage")
    admin_token: SecretStr | None = None
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    ml_device: str = "cuda"
    ml_models_dir: Path = Path.home() / ".cache" / "echosing" / "models"
    default_separation_preset: SeparationPreset = SeparationPreset.DEMUCS
    separation_timeout_s: float = Field(default=900.0, gt=0)
    demucs_model: str = "htdemucs"
    demucs_shifts: int = Field(default=5, ge=1)
    roformer_model: str = "melband_roformer_inst_v2.ckpt"
    roformer_normalization: float = Field(default=0.9, gt=0, le=1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Returns:
        The cached ``Settings`` object.
    """
    return Settings()
