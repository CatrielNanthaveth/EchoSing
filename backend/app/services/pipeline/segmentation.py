"""Ingestion stage 3: build the lyric lines of a song.

When the song has official lyrics, their text and line breaks are used and the
transcription only provides timings (``align_lyrics``). Otherwise the
transcribed words are grouped into lines heuristically (``segment_lines``).
"""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.songs import SongRepository
from app.schemas.analysis import LyricLine
from app.services.lyrics import (
    AlignmentReport,
    LyricsMismatchError,
    SegmentationConfig,
    align_lyrics,
    parse_lyrics_text,
    segment_lines,
)
from app.services.pipeline.errors import StageError
from app.services.pipeline.transcription import load_transcription
from app.storage.base import ObjectNotFoundError, StorageBackend
from app.storage.keys import work_key

LINES_ARTIFACT = "lines.json"


class SegmentedLyrics(BaseModel):
    """Lyric lines of a song, saved as an intermediate artifact.

    Attributes:
        source: ``official`` when the text comes from the song's lyrics,
            ``transcription`` when it comes from the transcriber.
        lines: Lyric lines with timed words.
        alignment: Quality of the alignment, for official lyrics.
    """

    source: Literal["official", "transcription"]
    lines: list[LyricLine]
    alignment: AlignmentReport | None = None


class SegmentationResult(BaseModel):
    """Outcome of the segmentation stage.

    Attributes:
        song_id: Id of the processed song.
        artifact_key: Storage key of the saved lines.
        lyrics: The lyric lines.
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
    """Builds a song's lyric lines from its transcription.

    It needs no GPU, so it can be re-run in seconds, e.g. after correcting the
    official lyrics or tuning ``SegmentationConfig``.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        config: SegmentationConfig | None = None,
    ) -> None:
        """Initialize the stage.

        Args:
            session: Database session, used to read the official lyrics.
            storage: Storage holding the transcription and receiving the lines.
            config: Thresholds of the heuristic segmentation fallback.
        """
        self._songs = SongRepository(session)
        self._storage = storage
        self._config = config or SegmentationConfig()

    async def run(self, song_id: uuid.UUID) -> SegmentationResult:
        """Build and save the lyric lines of a song.

        Args:
            song_id: Id of the song.

        Returns:
            The lines and where they were saved.

        Raises:
            StageError: If the song does not exist, has not been transcribed
                yet, or its official lyrics do not match the audio.
        """
        song = await self._songs.get(song_id)
        if song is None:
            raise StageError(f"Song {song_id} does not exist")
        try:
            transcription = await load_transcription(self._storage, song_id)
        except ObjectNotFoundError as error:
            raise StageError(
                f"Song {song_id} has no transcription; run the 'transcribe' stage first"
            ) from error

        official_lines = parse_lyrics_text(song.lyrics_text or "")
        if official_lines:
            try:
                aligned = align_lyrics(official_lines, transcription.words)
            except LyricsMismatchError as error:
                raise StageError(
                    f"Cannot use the lyrics of {song_id}: {error}"
                ) from error
            lyrics = SegmentedLyrics(
                source="official", lines=aligned.lines, alignment=aligned.report
            )
        else:
            lyrics = SegmentedLyrics(
                source="transcription",
                lines=segment_lines(transcription.words, self._config),
            )

        key = work_key(song_id, LINES_ARTIFACT)
        await self._storage.save(
            key, lyrics.model_dump_json(indent=2).encode(), "application/json"
        )
        return SegmentationResult(song_id=song_id, artifact_key=key, lyrics=lyrics)
