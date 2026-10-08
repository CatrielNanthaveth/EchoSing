"""Response schemas of the public song catalog."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import IngestionStage, SeparationPreset, SongStatus
from app.schemas.analysis import LyricLine


class SongSummary(BaseModel):
    """A playable song as listed in the catalog.

    Attributes:
        id: Song id.
        title: Song title.
        artist: Performing artist.
        language: ISO 639-1 code of the lyrics, if known.
        duration_ms: Duration of the song.
        line_count: Number of lyric lines (scoring units).
        reprocessing: True while a newer analysis is being produced; the song
            stays playable with its current one.
    """

    id: uuid.UUID
    title: str
    artist: str
    language: str | None
    duration_ms: int | None
    line_count: int
    reprocessing: bool


class SongPage(BaseModel):
    """A page of catalog songs.

    Attributes:
        items: Songs in this page, ordered by title.
        total: Songs matching the query across all pages.
        limit: Max songs per page requested.
        offset: Songs skipped before this page.
    """

    items: list[SongSummary]
    total: int
    limit: int
    offset: int


class SongDetail(SongSummary):
    """A playable song with its synced lyrics.

    Attributes:
        analysis_id: Id of the current analysis; play sessions are bound to it.
        analysis_version: Version number of the current analysis.
        lines: Lyric lines with timed words (the pitch curve is served apart).
    """

    analysis_id: uuid.UUID
    analysis_version: int
    lines: list[LyricLine]


class PitchResponse(BaseModel):
    """Reference pitch of a song, or of one of its lines.

    Attributes:
        analysis_id: Id of the analysis the curve belongs to.
        line_index: The requested line, or None for the whole song.
        start_ms: Time of the first frame returned.
        hop_ms: Time between frames.
        midi: Pitch per frame as fractional MIDI note; None without estimate.
        confidence: Voicing confidence per frame, 0-100.
    """

    analysis_id: uuid.UUID
    line_index: int | None
    start_ms: int
    hop_ms: int
    midi: list[float | None]
    confidence: list[int]


class JobReport(BaseModel):
    """State of an ingestion job.

    Attributes:
        id: Job id.
        stage: Current or final stage.
        task_id: Id of the queued task, if it was queued.
        error_message: Failure reason, if it failed.
        created_at: When the job was created.
        started_at: When processing started.
        finished_at: When it finished, successfully or not.
    """

    id: uuid.UUID
    stage: IngestionStage
    task_id: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SongStatusReport(BaseModel):
    """Ingestion status of a song, for administrators.

    Attributes:
        song_id: Song id.
        title: Song title.
        artist: Performing artist.
        status: Lifecycle status of the song.
        error_message: Last failure reason, if any.
        separation_preset: Preset used to split vocals and instrumental.
        has_lyrics: Whether official lyrics are loaded.
        duration_ms: Duration, once known.
        current_analysis_version: Version that is playable, if any.
        latest_job: Most recent ingestion job, if any.
    """

    song_id: uuid.UUID
    title: str
    artist: str
    status: SongStatus
    error_message: str | None
    separation_preset: SeparationPreset
    has_lyrics: bool
    duration_ms: int | None
    current_analysis_version: int | None
    latest_job: JobReport | None
