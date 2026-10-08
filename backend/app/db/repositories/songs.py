"""Persistence of songs and their analyses."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Song, SongAnalysis
from app.domain.enums import SeparationPreset, SongStatus


class SongRepository:
    """Data access for ``Song`` rows.

    Repositories flush but never commit: the calling service owns the
    transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    async def add(
        self,
        title: str,
        artist: str,
        language: str | None = None,
        separation_preset: SeparationPreset = SeparationPreset.DEMUCS,
    ) -> Song:
        """Create a song in ``PENDING`` status.

        Args:
            title: Song title.
            artist: Performing artist.
            language: ISO 639-1 code of the lyrics language, if known.
            separation_preset: How its vocals and instrumental will be split.

        Returns:
            The persisted song, with its generated id.
        """
        song = Song(
            title=title,
            artist=artist,
            language=language,
            separation_preset=separation_preset,
        )
        self._session.add(song)
        await self._session.flush()
        return song

    async def get(self, song_id: uuid.UUID) -> Song | None:
        """Fetch a song by id.

        Args:
            song_id: Id of the song.

        Returns:
            The song, or None if it does not exist.
        """
        return await self._session.get(Song, song_id)

    async def set_status(
        self,
        song_id: uuid.UUID,
        status: SongStatus,
        error_message: str | None = None,
    ) -> bool:
        """Update the status of a song.

        Args:
            song_id: Id of the song.
            status: New status.
            error_message: Failure reason; cleared when None.

        Returns:
            True if the song exists and was updated.
        """
        # Update through the ORM (not a bulk UPDATE) so any instance already in
        # the identity map reflects the change.
        song = await self._session.get(Song, song_id)
        if song is None:
            return False
        song.status = status
        song.error_message = error_message
        await self._session.flush()
        return True

    async def set_duration(self, song_id: uuid.UUID, duration_ms: int) -> bool:
        """Record the duration of a song.

        Args:
            song_id: Id of the song.
            duration_ms: Duration in milliseconds.

        Returns:
            True if the song exists and was updated.
        """
        song = await self._session.get(Song, song_id)
        if song is None:
            return False
        song.duration_ms = duration_ms
        await self._session.flush()
        return True

    async def set_lyrics(self, song_id: uuid.UUID, lyrics_text: str | None) -> bool:
        """Record the official lyrics of a song.

        Args:
            song_id: Id of the song.
            lyrics_text: Lyrics as plain text, or None to remove them.

        Returns:
            True if the song exists and was updated.
        """
        song = await self._session.get(Song, song_id)
        if song is None:
            return False
        song.lyrics_text = lyrics_text
        await self._session.flush()
        return True

    async def set_language(self, song_id: uuid.UUID, language: str) -> bool:
        """Record the lyrics language of a song.

        Args:
            song_id: Id of the song.
            language: Language code, e.g. ``es``.

        Returns:
            True if the song exists and was updated.
        """
        song = await self._session.get(Song, song_id)
        if song is None:
            return False
        song.language = language
        await self._session.flush()
        return True

    async def set_separation_preset(
        self, song_id: uuid.UUID, preset: SeparationPreset
    ) -> bool:
        """Record the separation preset of a song.

        Args:
            song_id: Id of the song.
            preset: Preset to use for (re)processing it.

        Returns:
            True if the song exists and was updated.
        """
        song = await self._session.get(Song, song_id)
        if song is None:
            return False
        song.separation_preset = preset
        await self._session.flush()
        return True

    async def list_by_status(
        self, status: SongStatus, *, limit: int = 50, offset: int = 0
    ) -> Sequence[Song]:
        """List songs in a given status, oldest first.

        Args:
            status: Status to filter by.
            limit: Max number of songs to return.
            offset: Number of songs to skip.

        Returns:
            The matching songs.
        """
        result = await self._session.scalars(
            select(Song)
            .where(Song.status == status)
            .order_by(Song.created_at, Song.id)
            .limit(limit)
            .offset(offset)
        )
        return result.all()


class SongAnalysisRepository:
    """Data access for versioned ``SongAnalysis`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    async def add_version(
        self, song_id: uuid.UUID, format_version: int, data: dict[str, Any]
    ) -> SongAnalysis:
        """Store a new analysis version and make it the current one.

        Args:
            song_id: Id of the analyzed song.
            format_version: Version of the JSON format of ``data``.
            data: Lyrics, timestamps and pitch curves.

        Returns:
            The new current analysis.
        """
        latest = await self._session.scalar(
            select(func.max(SongAnalysis.version)).where(
                SongAnalysis.song_id == song_id
            )
        )
        await self._session.execute(
            update(SongAnalysis)
            .where(SongAnalysis.song_id == song_id, SongAnalysis.is_current)
            .values(is_current=False)
            # Keep already-loaded analyses of this song in sync.
            .execution_options(synchronize_session="fetch")
        )
        analysis = SongAnalysis(
            song_id=song_id,
            version=(latest or 0) + 1,
            is_current=True,
            format_version=format_version,
            data=data,
        )
        self._session.add(analysis)
        await self._session.flush()
        return analysis

    async def get_current(self, song_id: uuid.UUID) -> SongAnalysis | None:
        """Fetch the current analysis of a song.

        Args:
            song_id: Id of the song.

        Returns:
            The current analysis, or None if the song has none.
        """
        return await self._session.scalar(
            select(SongAnalysis).where(
                SongAnalysis.song_id == song_id, SongAnalysis.is_current
            )
        )
