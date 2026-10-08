"""Final ingestion stage: publish the song analysis and mark the song ready."""

import uuid

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.domain.enums import SongStatus
from app.schemas.analysis import FORMAT_VERSION, PipelineInfo, SongAnalysisData
from app.services.pipeline.errors import StageError
from app.services.pipeline.manifest import load_manifest
from app.services.pipeline.pitch import load_pitch
from app.services.pipeline.segmentation import load_lines
from app.storage.base import ObjectNotFoundError, StorageBackend


class PersistResult(BaseModel):
    """Outcome of the persist stage.

    Attributes:
        song_id: Id of the song.
        analysis_id: Id of the stored analysis version.
        version: Version number of the analysis for this song.
        lines: Number of lyric lines.
        frames: Number of pitch frames.
        pipeline: Models that produced the analysis.
    """

    song_id: uuid.UUID
    analysis_id: uuid.UUID
    version: int
    lines: int
    frames: int
    pipeline: PipelineInfo


class PersistStage:
    """Builds the ``SongAnalysisData`` from the stage artifacts and stores it.

    Each run stores a new analysis version and makes it current; play sessions
    keep pointing at the version they were scored against.
    """

    def __init__(self, session: AsyncSession, storage: StorageBackend) -> None:
        """Initialize the stage.

        Args:
            session: Database session; this stage commits its own changes.
            storage: Storage holding the stage artifacts.
        """
        self._session = session
        self._storage = storage
        self._songs = SongRepository(session)
        self._analyses = SongAnalysisRepository(session)

    async def run(self, song_id: uuid.UUID) -> PersistResult:
        """Validate and publish the analysis of a song.

        Args:
            song_id: Id of the song.

        Returns:
            The stored analysis version.

        Raises:
            StageError: If the song, an artifact or a model record is missing,
                or the assembled analysis is invalid. Nothing is stored then.
        """
        song = await self._songs.get(song_id)
        if song is None:
            raise StageError(f"Song {song_id} does not exist")
        if song.duration_ms is None:
            raise StageError(f"Song {song_id} has no duration; run 'separate' first")
        try:
            lyrics = await load_lines(self._storage, song_id)
        except ObjectNotFoundError as error:
            raise StageError(
                f"Song {song_id} has no lines; run 'segment' first"
            ) from error
        try:
            pitch = await load_pitch(self._storage, song_id)
        except ObjectNotFoundError as error:
            raise StageError(
                f"Song {song_id} has no pitch; run 'pitch' first"
            ) from error

        manifest = await load_manifest(self._storage, song_id)
        if (
            manifest.separator is None
            or manifest.transcriber is None
            or manifest.pitch_extractor is None
        ):
            missing = [name for name, value in manifest if value is None]
            raise StageError(
                f"Song {song_id} is missing the model of: {', '.join(missing)}"
            )
        pipeline = PipelineInfo(
            separator=manifest.separator,
            transcriber=manifest.transcriber,
            pitch_extractor=manifest.pitch_extractor,
            language=song.language,
        )

        try:
            analysis = SongAnalysisData(
                duration_ms=song.duration_ms,
                pipeline=pipeline,
                lines=lyrics.lines,
                pitch=pitch,
            )
        except ValidationError as error:
            first = error.errors()[0]
            raise StageError(
                f"The analysis of {song_id} is invalid: {first['msg']} "
                f"(at {'.'.join(str(part) for part in first['loc'])})"
            ) from error

        try:
            stored = await self._analyses.add_version(
                song_id, FORMAT_VERSION, analysis.model_dump(mode="json")
            )
            await self._songs.set_status(song_id, SongStatus.READY)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

        return PersistResult(
            song_id=song_id,
            analysis_id=stored.id,
            version=stored.version,
            lines=len(analysis.lines),
            frames=analysis.pitch.frame_count,
            pipeline=pipeline,
        )
