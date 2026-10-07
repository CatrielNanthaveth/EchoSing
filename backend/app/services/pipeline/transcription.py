"""Ingestion stage 2: transcribe the isolated vocals with word timestamps."""

import tempfile
import uuid
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.transcription import Transcriber, Transcription, WhisperTranscriber
from app.services.pipeline.errors import StageError
from app.storage.base import StorageBackend
from app.storage.keys import work_key

TRANSCRIPTION_ARTIFACT = "transcription.json"


class TranscriptionResult(BaseModel):
    """Outcome of the transcription stage.

    Attributes:
        song_id: Id of the processed song.
        artifact_key: Storage key of the saved transcription.
        transcription: The transcription itself.
    """

    song_id: uuid.UUID
    artifact_key: str
    transcription: Transcription


async def load_transcription(
    storage: StorageBackend, song_id: uuid.UUID
) -> Transcription:
    """Read the transcription saved by this stage.

    Args:
        storage: Storage backend.
        song_id: Id of the song.

    Returns:
        The saved transcription.

    Raises:
        app.storage.base.ObjectNotFoundError: If the stage has not run yet.
    """
    key = work_key(song_id, TRANSCRIPTION_ARTIFACT)
    content = b"".join([chunk async for chunk in await storage.stream(key)])
    return Transcription.model_validate_json(content)


class TranscriptionStage:
    """Transcribes a song's isolated vocals and saves the result.

    The transcription is stored as an intermediate artifact so that the
    segmentation stage can be re-run without repeating GPU work.
    """

    def __init__(
        self, session: AsyncSession, storage: StorageBackend, transcriber: Transcriber
    ) -> None:
        """Initialize the stage.

        Args:
            session: Database session; this stage commits its own changes.
            storage: Storage holding the vocals and receiving the artifact.
            transcriber: Speech recognition model.
        """
        self._session = session
        self._storage = storage
        self._transcriber = transcriber
        self._songs = SongRepository(session)
        self._assets = SongAssetRepository(session)

    async def run(self, song_id: uuid.UUID) -> TranscriptionResult:
        """Transcribe a song.

        The song's language is passed to the transcriber when known; otherwise
        the detected language is saved on the song.

        Args:
            song_id: Id of the song to process.

        Returns:
            The transcription and where it was saved.

        Raises:
            StageError: If the song or its vocals are missing.
            app.ml.transcription.TranscriptionError: If transcription fails.
        """
        song = await self._songs.get(song_id)
        if song is None:
            raise StageError(f"Song {song_id} does not exist")
        vocals = await self._assets.get(song_id, AssetKind.VOCALS)
        if vocals is None:
            raise StageError(
                f"Song {song_id} has no vocals; run the 'separate' stage first"
            )
        known_language = song.language

        with tempfile.TemporaryDirectory(prefix="echosing-transcription-") as tmp:
            async with self._storage.local_path(vocals.storage_key) as audio:
                transcription = await self._transcriber.transcribe(
                    audio, Path(tmp), known_language
                )

        key = work_key(song_id, TRANSCRIPTION_ARTIFACT)
        await self._storage.save(
            key, transcription.model_dump_json(indent=2).encode(), "application/json"
        )

        if known_language is None and transcription.language:
            try:
                await self._songs.set_language(song_id, transcription.language)
                await self._session.commit()
            except BaseException:
                await self._session.rollback()
                raise

        return TranscriptionResult(
            song_id=song_id, artifact_key=key, transcription=transcription
        )


def build_transcription_stage(
    session: AsyncSession, storage: StorageBackend, settings: Settings
) -> TranscriptionStage:
    """Create a transcription stage using Whisper as configured in the settings.

    Args:
        session: Database session.
        storage: Storage backend.
        settings: Application settings.

    Returns:
        The configured stage.
    """
    transcriber = WhisperTranscriber(
        model=settings.whisper_model,
        device=settings.ml_device,
        timeout_s=settings.transcription_timeout_s,
        hallucination_silence_s=settings.whisper_hallucination_silence_s,
    )
    return TranscriptionStage(session, storage, transcriber)
