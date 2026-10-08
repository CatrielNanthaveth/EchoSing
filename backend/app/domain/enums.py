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
        ROFORMER: BS-RoFormer model (audio-separator). Several times slower and
            heavier on VRAM, but cleaner on some songs.
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


class Difficulty(StrEnum):
    """How far from the note singing still earns credit.

    Attributes:
        EASY: Full credit within 1 semitone, none from 3.
        NORMAL: Full credit within 3/4 of a semitone, none from 2.5.
        HARD: Full credit within half a semitone, none from 2.
    """

    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"


class PlaySessionStatus(StrEnum):
    """Lifecycle of a karaoke play session."""

    ACTIVE = "active"
    FINISHED = "finished"
