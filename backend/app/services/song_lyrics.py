"""Management of the official lyrics of catalog songs."""

import uuid
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.songs import SongRepository
from app.db.session import get_db_session
from app.services.errors import SongNotFoundError
from app.services.lyrics import MAX_LYRICS_CHARS, parse_lyrics_text

__all__ = [
    "EmptyLyricsError",
    "LyricsSummary",
    "LyricsUpdate",
    "SongLyricsService",
    "SongNotFoundError",
    "get_song_lyrics_service",
]


class EmptyLyricsError(ValueError):
    """The lyrics contain no sung line."""


class LyricsUpdate(BaseModel):
    """Official lyrics submitted for a song.

    Attributes:
        lyrics: Plain text, one verse per line. Empty lines, ``[Section]``
            labels and lines fully in parentheses are ignored.
    """

    lyrics: str = Field(min_length=1, max_length=MAX_LYRICS_CHARS)


class LyricsSummary(BaseModel):
    """Result of saving the lyrics of a song.

    Attributes:
        song_id: Id of the song.
        lines: Number of sung lines found in the lyrics.
    """

    song_id: uuid.UUID
    lines: int


class SongLyricsService:
    """Stores the official lyrics used to time and display a song."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: Database session; this service commits its own changes.
        """
        self._session = session
        self._songs = SongRepository(session)

    async def set_lyrics(self, song_id: uuid.UUID, lyrics: str) -> LyricsSummary:
        """Save the official lyrics of a song.

        They take effect the next time the song's lines are built (the
        ``segment`` stage), replacing the transcription-based lines.

        Args:
            song_id: Id of the song.
            lyrics: Lyrics as plain text.

        Returns:
            How many sung lines were found.

        Raises:
            EmptyLyricsError: If the text has no sung line.
            SongNotFoundError: If the song does not exist.
        """
        lines = parse_lyrics_text(lyrics)
        if not lines:
            raise EmptyLyricsError("The lyrics contain no sung line")
        if not await self._songs.set_lyrics(song_id, lyrics):
            raise SongNotFoundError(f"Song {song_id} does not exist")
        await self._session.commit()
        return LyricsSummary(song_id=song_id, lines=len(lines))


def get_song_lyrics_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SongLyricsService:
    """Provide a ``SongLyricsService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return SongLyricsService(session)
