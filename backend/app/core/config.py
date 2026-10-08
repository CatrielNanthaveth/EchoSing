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
        whisper_model: Whisper model used to transcribe the isolated vocals.
        transcription_timeout_s: Max seconds one transcription may take.
        whisper_hallucination_silence_s: Whisper's own hallucination filter
            (skips suspicious segments around silences longer than this, in
            seconds). Disabled by default: on fast sung lyrics it drops real
            words; known hallucinations are filtered after transcription.
        crepe_model: torchcrepe model capacity (``full`` or ``tiny``).
        crepe_decoder: torchcrepe decoder (``viterbi``, ``weighted_argmax`` or
            ``argmax``); viterbi reduces octave jumps.
        crepe_fmin_hz: Lowest pitch considered.
        crepe_fmax_hz: Highest pitch considered.
        crepe_batch_size: Frames per inference batch.
        pitch_timeout_s: Max seconds one pitch extraction may take.
        voicing_min_confidence: Confidence (0-100) from which a frame counts as
            sung, used to detect hallucinated words.
        hallucination_max_voiced_ratio: Words whose fraction of sung frames is
            below this count as unvoiced.
        hallucination_min_run_words: Consecutive unvoiced words needed to treat
            them as a hallucinated phrase (isolated ones are common in rap).
        hallucination_voicing_filter: Whether hallucinated phrases are
            discarded from the transcription (otherwise only reported).
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
    roformer_model: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
    roformer_normalization: float = Field(default=0.9, gt=0, le=1)
    whisper_model: str = "large-v3-turbo"
    transcription_timeout_s: float = Field(default=900.0, gt=0)
    whisper_hallucination_silence_s: float | None = Field(default=None, gt=0)
    crepe_model: str = "full"
    crepe_decoder: str = "viterbi"
    crepe_fmin_hz: float = Field(default=65.0, gt=0)
    crepe_fmax_hz: float = Field(default=1100.0, gt=0)
    crepe_batch_size: int = Field(default=1024, gt=0)
    pitch_timeout_s: float = Field(default=900.0, gt=0)
    voicing_min_confidence: int = Field(default=50, ge=0, le=100)
    hallucination_max_voiced_ratio: float = Field(default=0.05, ge=0, le=1)
    hallucination_min_run_words: int = Field(default=3, ge=1)
    hallucination_voicing_filter: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Returns:
        The cached ``Settings`` object.
    """
    return Settings()
