"""Ingestion stage 1: split the original song into vocals and instrumental."""

import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind, SeparationPreset
from app.ml.audio import probe_duration_ms, transcode_to_mp3
from app.ml.separation import DemucsSeparator, RoformerSeparator, SourceSeparator
from app.services.pipeline.errors import StageError
from app.services.pipeline.manifest import update_manifest
from app.storage.base import StorageBackend, StoredObject
from app.storage.keys import asset_key

DurationProbe = Callable[[Path], Awaitable[int]]
Mp3Encoder = Callable[[Path, Path], Awaitable[None]]
SeparatorFactory = Callable[[SeparationPreset], SourceSeparator]


class SeparationResult(BaseModel):
    """Outcome of the separation stage.

    Attributes:
        song_id: Id of the processed song.
        duration_ms: Duration of the original audio.
        preset: Separation preset that was used.
        separator: Model configuration that produced the stems.
        vocals: Stored isolated vocals (FLAC, input for transcription/pitch).
        instrumental: Stored karaoke track (MP3, streamed to clients).
    """

    song_id: uuid.UUID
    duration_ms: int
    preset: SeparationPreset
    separator: str
    vocals: StoredObject
    instrumental: StoredObject


class SeparationStage:
    """Produces the vocals and instrumental assets of a song.

    The separator is chosen from the song's ``separation_preset``. Running the
    stage again on the same song replaces the previous stems.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        separator_factory: SeparatorFactory,
        *,
        probe: DurationProbe = probe_duration_ms,
        encode_mp3: Mp3Encoder = transcode_to_mp3,
    ) -> None:
        """Initialize the stage.

        Args:
            session: Database session; this stage commits its own changes.
            storage: Storage holding the original and receiving the stems.
            separator_factory: Builds the separator for a preset.
            probe: Returns the duration of an audio file, validating it.
            encode_mp3: Encodes an audio file as MP3.
        """
        self._session = session
        self._storage = storage
        self._separator_factory = separator_factory
        self._probe = probe
        self._encode_mp3 = encode_mp3
        self._songs = SongRepository(session)
        self._assets = SongAssetRepository(session)

    async def run(
        self, song_id: uuid.UUID, preset: SeparationPreset | None = None
    ) -> SeparationResult:
        """Separate a song and store its stems.

        Args:
            song_id: Id of the song to process.
            preset: Preset to use instead of the song's own. On success it
                becomes the song's preset, so re-processing is reproducible.

        Returns:
            The stored stems and the song duration.

        Raises:
            StageError: If the song or its original file is missing.
            app.ml.audio.InvalidAudioError: If the original is not valid audio.
            app.ml.separation.SeparationError: If the separator fails.
            app.ml.tools.ToolError: If the MP3 encoding fails.
        """
        song = await self._songs.get(song_id)
        if song is None:
            raise StageError(f"Song {song_id} does not exist")
        original = await self._assets.get(song_id, AssetKind.ORIGINAL)
        if original is None:
            raise StageError(f"Song {song_id} has no original audio")
        chosen = preset or song.separation_preset
        separator = self._separator_factory(chosen)

        with tempfile.TemporaryDirectory(prefix="echosing-separation-") as tmp:
            work_dir = Path(tmp)
            async with self._storage.local_path(original.storage_key) as source:
                duration_ms = await self._probe(source)
                stems = await separator.separate(source, work_dir / "stems")

            instrumental_mp3 = work_dir / "instrumental.mp3"
            await self._encode_mp3(stems.accompaniment, instrumental_mp3)

            vocals = await self._storage.save_file(
                asset_key(song_id, AssetKind.VOCALS, "flac"), stems.vocals, "audio/flac"
            )
            instrumental = await self._storage.save_file(
                asset_key(song_id, AssetKind.INSTRUMENTAL, "mp3"),
                instrumental_mp3,
                "audio/mpeg",
            )

        try:
            await self._assets.upsert(song_id, AssetKind.VOCALS, vocals)
            await self._assets.upsert(song_id, AssetKind.INSTRUMENTAL, instrumental)
            await self._songs.set_duration(song_id, duration_ms)
            await self._songs.set_separation_preset(song_id, chosen)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

        await update_manifest(self._storage, song_id, separator=separator.name)
        return SeparationResult(
            song_id=song_id,
            duration_ms=duration_ms,
            preset=chosen,
            separator=separator.name,
            vocals=vocals,
            instrumental=instrumental,
        )


def build_separator(preset: SeparationPreset, settings: Settings) -> SourceSeparator:
    """Create the separator of a preset, configured from the settings.

    Args:
        preset: Separation preset.
        settings: Application settings.

    Returns:
        The separator implementing the preset.
    """
    if preset is SeparationPreset.ROFORMER:
        return RoformerSeparator(
            model=settings.roformer_model,
            models_dir=settings.ml_models_dir,
            normalization=settings.roformer_normalization,
            timeout_s=settings.separation_timeout_s,
        )
    return DemucsSeparator(
        model=settings.demucs_model,
        device=settings.ml_device,
        timeout_s=settings.separation_timeout_s,
        shifts=settings.demucs_shifts,
    )


def build_separation_stage(
    session: AsyncSession, storage: StorageBackend, settings: Settings
) -> SeparationStage:
    """Create a separation stage whose separators follow the settings.

    Args:
        session: Database session.
        storage: Storage backend.
        settings: Application settings.

    Returns:
        The configured stage.
    """
    return SeparationStage(
        session, storage, lambda preset: build_separator(preset, settings)
    )
