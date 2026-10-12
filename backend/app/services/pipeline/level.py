"""Ingestion stage: loudness envelope of the isolated vocals (rap mode).

Light (FFmpeg + numpy, no GPU): it can run on existing songs on its own,
followed by ``persist`` to publish an analysis that includes it.
"""

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.level import extract_level
from app.schemas.analysis import LevelCurve
from app.services.pipeline.errors import StageError
from app.storage.base import StorageBackend
from app.storage.keys import work_key

LEVEL_ARTIFACT = "level.json"

LevelExtractor = Callable[[Path], Awaitable[LevelCurve]]


class LevelResult(BaseModel):
    """Outcome of the level stage.

    Attributes:
        song_id: Id of the processed song.
        artifact_key: Storage key of the saved curve.
        frame_count: Number of frames in the curve.
    """

    song_id: uuid.UUID
    artifact_key: str
    frame_count: int


async def load_level(storage: StorageBackend, song_id: uuid.UUID) -> LevelCurve:
    """Read the level curve saved by this stage.

    Args:
        storage: Storage backend.
        song_id: Id of the song.

    Returns:
        The saved curve.

    Raises:
        app.storage.base.ObjectNotFoundError: If the stage has not run yet.
    """
    key = work_key(song_id, LEVEL_ARTIFACT)
    content = b"".join([chunk async for chunk in await storage.stream(key)])
    return LevelCurve.model_validate_json(content)


class LevelStage:
    """Measures and saves the loudness envelope of a song's vocals."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        extractor: LevelExtractor = extract_level,
    ) -> None:
        """Initialize the stage.

        Args:
            session: Database session, used to find the vocals asset.
            storage: Storage holding the vocals and receiving the curve.
            extractor: Measures the level of an audio file.
        """
        self._songs = SongRepository(session)
        self._assets = SongAssetRepository(session)
        self._storage = storage
        self._extractor = extractor

    async def run(self, song_id: uuid.UUID) -> LevelResult:
        """Measure the vocals' level of a song.

        Args:
            song_id: Id of the song.

        Returns:
            Where the curve was saved and its size.

        Raises:
            StageError: If the song or its vocals are missing.
            app.ml.tools.ToolError: If decoding fails.
        """
        if await self._songs.get(song_id) is None:
            raise StageError(f"Song {song_id} does not exist")
        vocals = await self._assets.get(song_id, AssetKind.VOCALS)
        if vocals is None:
            raise StageError(
                f"Song {song_id} has no vocals; run the 'separate' stage first"
            )
        async with self._storage.local_path(vocals.storage_key) as audio:
            curve = await self._extractor(audio)

        key = work_key(song_id, LEVEL_ARTIFACT)
        await self._storage.save(
            key, curve.model_dump_json().encode(), "application/json"
        )
        return LevelResult(
            song_id=song_id, artifact_key=key, frame_count=curve.frame_count
        )
