"""Registration of new songs in the catalog and scheduling of their ingestion."""

import uuid
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import PurePath
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import IngestionJob, Song
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.db.session import get_db_session
from app.domain.enums import AssetKind, IngestionStage, SeparationPreset, SongStatus
from app.storage.base import StorageBackend
from app.storage.dependencies import get_storage
from app.storage.keys import asset_key, song_prefix
from app.workers.queue import JobQueue, QueueUnavailableError, get_job_queue

AUDIO_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
}


class UnsupportedAudioFormatError(Exception):
    """The uploaded file does not have a supported audio extension."""


class UploadTooLargeError(Exception):
    """The uploaded file exceeds the configured size limit."""


class NewSong(BaseModel):
    """Metadata of a song to add to the catalog.

    Attributes:
        title: Song title.
        artist: Performing artist.
        language: ISO 639-1 code of the lyrics language, if known.
        separation_preset: How to split vocals and instrumental; the service
            default applies when None.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    separation_preset: SeparationPreset | None = None


class SongRegistration(BaseModel):
    """Result of registering a song.

    Attributes:
        song_id: Id of the new song.
        job_id: Id of the ingestion job created for it.
        status: Status of the song.
        stage: Stage of the ingestion job.
        separation_preset: Preset that will be used to split the song.
    """

    song_id: uuid.UUID
    job_id: uuid.UUID
    status: SongStatus
    stage: IngestionStage
    separation_preset: SeparationPreset


class SongIngestionService:
    """Registers uploaded songs and schedules their ingestion pipeline."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        queue: JobQueue,
        max_upload_bytes: int,
        default_preset: SeparationPreset = SeparationPreset.DEMUCS,
    ) -> None:
        """Initialize the service.

        Args:
            session: Database session; this service owns its transactions.
            storage: Where the original audio file is stored.
            queue: Queue that runs the ingestion pipeline.
            max_upload_bytes: Max accepted size of the audio file.
            default_preset: Separation preset for songs that do not choose one.
        """
        self._session = session
        self._storage = storage
        self._queue = queue
        self._max_upload_bytes = max_upload_bytes
        self._default_preset = default_preset
        self._songs = SongRepository(session)
        self._assets = SongAssetRepository(session)
        self._jobs = IngestionJobRepository(session)

    async def register_song(
        self, song: NewSong, filename: str, content: AsyncIterable[bytes]
    ) -> SongRegistration:
        """Store a new song and queue its ingestion.

        The song, its original file and its job are committed together before
        the job is queued, so the worker always finds them. If anything fails
        before the commit, nothing is left behind (no rows, no file).

        Args:
            song: Song metadata.
            filename: Original file name, used for its extension.
            content: Audio file content as a stream of chunks.

        Returns:
            Ids and initial states of the song and its job.

        Raises:
            UnsupportedAudioFormatError: If the extension is not supported.
            UploadTooLargeError: If the content exceeds the size limit.
            QueueUnavailableError: If the job could not be queued; the song and
                job are then persisted as ``failed``.
        """
        extension = PurePath(filename).suffix.lower().removeprefix(".")
        content_type = AUDIO_CONTENT_TYPES.get(extension)
        if content_type is None:
            raise UnsupportedAudioFormatError(
                f"Unsupported audio file {filename!r}; expected one of "
                f"{', '.join(sorted(AUDIO_CONTENT_TYPES))}"
            )

        record, job = await self._persist(song, extension, content_type, content)

        try:
            task_id = await self._queue.enqueue_ingestion(job.id)
        except QueueUnavailableError as error:
            await self._mark_failed(record, job, str(error))
            raise

        await self._jobs.set_task_id(job, task_id)
        await self._session.commit()
        return SongRegistration(
            song_id=record.id,
            job_id=job.id,
            status=record.status,
            stage=job.stage,
            separation_preset=record.separation_preset,
        )

    async def _persist(
        self,
        song: NewSong,
        extension: str,
        content_type: str,
        content: AsyncIterable[bytes],
    ) -> tuple[Song, IngestionJob]:
        """Create the song, store its file and create its job in one commit."""
        # Keep the id in a plain variable: ORM instances may be expired by the
        # rollback below, and reading their attributes would then hit the DB.
        song_id: uuid.UUID | None = None
        try:
            record = await self._songs.add(
                song.title,
                song.artist,
                song.language,
                song.separation_preset or self._default_preset,
            )
            song_id = record.id
            stored = await self._storage.save(
                asset_key(record.id, AssetKind.ORIGINAL, extension),
                self._limit_size(content),
                content_type,
            )
            await self._assets.add(record.id, AssetKind.ORIGINAL, stored)
            job = await self._jobs.add(record.id)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            if song_id is not None:
                await self._storage.delete_prefix(song_prefix(song_id))
            raise
        return record, job

    async def _mark_failed(self, song: Song, job: IngestionJob, reason: str) -> None:
        """Persist a song and its job as failed."""
        await self._songs.set_status(song.id, SongStatus.FAILED, reason)
        await self._jobs.set_stage(job, IngestionStage.FAILED, error_message=reason)
        await self._session.commit()

    async def _limit_size(self, content: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
        """Pass chunks through, failing once the size limit is exceeded."""
        received = 0
        async for chunk in content:
            received += len(chunk)
            if received > self._max_upload_bytes:
                raise UploadTooLargeError(
                    f"File exceeds the limit of {self._max_upload_bytes} bytes"
                )
            yield chunk


def get_song_ingestion_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SongIngestionService:
    """Provide a ``SongIngestionService`` wired to the real dependencies.

    Args:
        session: Request-scoped database session.
        storage: Storage backend.
        queue: Job queue.
        settings: Application settings.

    Returns:
        The service.
    """
    return SongIngestionService(
        session,
        storage,
        queue,
        settings.max_upload_bytes,
        settings.default_separation_preset,
    )
