"""Public song catalog: listing, search and song details."""

import uuid
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.catalog import CatalogRepository, PlayableSong
from app.db.repositories.song_assets import SongAssetRepository
from app.db.session import get_db_session
from app.domain.enums import AssetKind, SongStatus
from app.schemas.analysis import LyricLine
from app.schemas.catalog import SongDetail, SongPage, SongSummary
from app.services.errors import SongNotFoundError

_LINES = TypeAdapter(list[LyricLine])
_IN_PROGRESS = (SongStatus.PENDING, SongStatus.PROCESSING)


class InstrumentalAudio(BaseModel):
    """Location of a song's karaoke track.

    Attributes:
        storage_key: Storage key of the audio file.
        content_type: Its media type.
    """

    storage_key: str
    content_type: str


def _summary(playable: PlayableSong) -> SongSummary:
    song = playable.song
    return SongSummary(
        id=song.id,
        title=song.title,
        artist=song.artist,
        language=song.language,
        duration_ms=song.duration_ms,
        line_count=playable.line_count,
        reprocessing=song.status in _IN_PROGRESS,
    )


class CatalogService:
    """Read-only access to the playable songs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: Database session.
        """
        self._catalog = CatalogRepository(session)
        self._assets = SongAssetRepository(session)

    async def get_instrumental(self, song_id: uuid.UUID) -> InstrumentalAudio:
        """Locate the karaoke track of a playable song.

        Args:
            song_id: Id of the song.

        Returns:
            Where the instrumental is stored and its media type.

        Raises:
            SongNotFoundError: If the song does not exist or is not playable.
        """
        asset = (
            await self._assets.get(song_id, AssetKind.INSTRUMENTAL)
            if await self._catalog.get_playable(song_id)
            else None
        )
        if asset is None:
            raise SongNotFoundError(f"Song {song_id} is not available")
        return InstrumentalAudio(
            storage_key=asset.storage_key, content_type=asset.content_type
        )

    async def list_songs(self, query: str | None, limit: int, offset: int) -> SongPage:
        """List playable songs, optionally filtered by title or artist.

        Args:
            query: Case-insensitive text searched in title and artist.
            limit: Max songs per page.
            offset: Songs to skip.

        Returns:
            The requested page.
        """
        songs, total = await self._catalog.list_playable(query, limit, offset)
        return SongPage(
            items=[_summary(song) for song in songs],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_song(self, song_id: uuid.UUID) -> SongDetail:
        """Get a playable song with its synced lyrics.

        Args:
            song_id: Id of the song.

        Returns:
            The song, its current analysis identity and its lyric lines.

        Raises:
            SongNotFoundError: If the song does not exist or is not playable.
        """
        playable = await self._catalog.get_playable(song_id)
        current = await self._catalog.get_current_lines(song_id)
        if playable is None or current is None:
            raise SongNotFoundError(f"Song {song_id} is not available")
        return SongDetail(
            **_summary(playable).model_dump(),
            analysis_id=current.analysis_id,
            analysis_version=current.version,
            lines=_LINES.validate_python(current.lines),
        )


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CatalogService:
    """Provide a ``CatalogService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return CatalogService(session)
