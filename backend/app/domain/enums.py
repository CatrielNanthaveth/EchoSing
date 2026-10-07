"""Domain enumerations shared by ORM models and Pydantic schemas."""

from enum import StrEnum


class SongStatus(StrEnum):
    """Lifecycle of a song in the catalog."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AssetKind(StrEnum):
    """Kind of audio file stored for a song."""

    ORIGINAL = "original"
    VOCALS = "vocals"
    INSTRUMENTAL = "instrumental"


class SeparationPreset(StrEnum):
    """Source separation configuration chosen for a song.

    Attributes:
        DEMUCS: Demucs ``htdemucs`` with several shifts. Fast, light on VRAM.
        ROFORMER: Mel-Band RoFormer instrumental model. Slower and heavier, but
            it can preserve more of the instrumental on some songs.
    """

    DEMUCS = "demucs"
    ROFORMER = "roformer"


class IngestionStage(StrEnum):
    """Current stage of an ingestion job."""

    QUEUED = "queued"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    EXTRACTING_PITCH = "extracting_pitch"
    PERSISTING = "persisting"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether the job has finished, successfully or not."""
        return self in (IngestionStage.DONE, IngestionStage.FAILED)


class PlaySessionStatus(StrEnum):
    """Lifecycle of a karaoke play session."""

    ACTIVE = "active"
    FINISHED = "finished"
