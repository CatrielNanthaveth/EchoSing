"""Ingestion stage 3: group the transcribed words into lyric lines."""

import uuid

from pydantic import BaseModel

from app.schemas.analysis import LyricLine
from app.services.lyrics import SegmentationConfig, segment_lines
from app.services.pipeline.errors import StageError
from app.services.pipeline.transcription import load_transcription
from app.storage.base import ObjectNotFoundError, StorageBackend
from app.storage.keys import work_key

LINES_ARTIFACT = "lines.json"


class SegmentedLyrics(BaseModel):
    """Lyric lines of a song, saved as an intermediate artifact.

    Attributes:
        source: Where the text comes from (``transcription`` for now; official
            lyrics are added by a later stage).
        lines: Lyric lines with timed words.
    """

    source: str
    lines: list[LyricLine]


class SegmentationResult(BaseModel):
    """Outcome of the segmentation stage.

    Attributes:
        song_id: Id of the processed song.
        artifact_key: Storage key of the saved lines.
        lyrics: The segmented lyrics.
    """

    song_id: uuid.UUID
    artifact_key: str
    lyrics: SegmentedLyrics


async def load_lines(storage: StorageBackend, song_id: uuid.UUID) -> SegmentedLyrics:
    """Read the lines saved by this stage.

    Args:
        storage: Storage backend.
        song_id: Id of the song.

    Returns:
        The saved lyrics.

    Raises:
        app.storage.base.ObjectNotFoundError: If the stage has not run yet.
    """
    key = work_key(song_id, LINES_ARTIFACT)
    content = b"".join([chunk async for chunk in await storage.stream(key)])
    return SegmentedLyrics.model_validate_json(content)


class SegmentationStage:
    """Splits a song's transcription into lyric lines.

    It needs neither the GPU nor the database, so it can be re-run in seconds
    while tuning ``SegmentationConfig``.
    """

    def __init__(
        self, storage: StorageBackend, config: SegmentationConfig | None = None
    ) -> None:
        """Initialize the stage.

        Args:
            storage: Storage holding the transcription and receiving the lines.
            config: Segmentation thresholds.
        """
        self._storage = storage
        self._config = config or SegmentationConfig()

    async def run(self, song_id: uuid.UUID) -> SegmentationResult:
        """Segment a song's transcription and save the lines.

        Args:
            song_id: Id of the song.

        Returns:
            The lines and where they were saved.

        Raises:
            StageError: If the song has not been transcribed yet.
        """
        try:
            transcription = await load_transcription(self._storage, song_id)
        except ObjectNotFoundError as error:
            raise StageError(
                f"Song {song_id} has no transcription; run the 'transcribe' stage first"
            ) from error

        lyrics = SegmentedLyrics(
            source="transcription",
            lines=segment_lines(transcription.words, self._config),
        )
        key = work_key(song_id, LINES_ARTIFACT)
        await self._storage.save(
            key, lyrics.model_dump_json(indent=2).encode(), "application/json"
        )
        return SegmentationResult(song_id=song_id, artifact_key=key, lyrics=lyrics)
