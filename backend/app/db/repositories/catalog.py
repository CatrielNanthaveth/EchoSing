"""Read-only queries of the public song catalog.

A song is *playable* when it has a current analysis and an instrumental
asset, whatever its status: a song being reprocessed stays playable with its
current analysis.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Song, SongAnalysis, SongAsset
from app.domain.enums import AssetKind


@dataclass(frozen=True)
class PlayableSong:
    """A playable song with the size of its current analysis.

    Attributes:
        song: The song row.
        line_count: Number of lyric lines in its current analysis.
    """

    song: Song
    line_count: int


class CurrentAnalysisLines(BaseModel):
    """The lyric lines of a song's current analysis, without the pitch curve.

    Attributes:
        analysis_id: Id of the analysis.
        version: Version number of the analysis.
        format_version: Format version of the analysis data.
        lines: Raw ``lines`` value of the analysis data.
    """

    analysis_id: uuid.UUID
    version: int
    format_version: int
    lines: list[dict[str, Any]]


def _escape_like(text: str) -> str:
    """Escape the LIKE wildcards of user input."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CatalogRepository:
    """Queries over playable songs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    def _playable(self) -> Select[Song, int]:
        has_instrumental = exists().where(
            SongAsset.song_id == Song.id, SongAsset.kind == AssetKind.INSTRUMENTAL
        )
        return (
            select(Song, func.jsonb_array_length(SongAnalysis.data["lines"]))
            .join(
                SongAnalysis,
                and_(SongAnalysis.song_id == Song.id, SongAnalysis.is_current),
            )
            .where(has_instrumental)
        )

    async def list_playable(
        self, query: str | None, limit: int, offset: int
    ) -> tuple[Sequence[PlayableSong], int]:
        """List playable songs ordered by title.

        Args:
            query: Case-insensitive text searched in title and artist.
            limit: Max songs to return.
            offset: Songs to skip.

        Returns:
            The page of songs and the total number of matches.
        """
        statement = self._playable()
        if query:
            pattern = f"%{_escape_like(query)}%"
            statement = statement.where(
                or_(
                    Song.title.ilike(pattern, escape="\\"),
                    Song.artist.ilike(pattern, escape="\\"),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = await self._session.execute(
            statement.order_by(func.lower(Song.title), Song.id)
            .limit(limit)
            .offset(offset)
        )
        songs = [PlayableSong(song=song, line_count=count) for song, count in rows]
        return songs, int(total or 0)

    async def get_playable(self, song_id: uuid.UUID) -> PlayableSong | None:
        """Fetch a playable song.

        Args:
            song_id: Id of the song.

        Returns:
            The song, or None if it does not exist or is not playable.
        """
        row = (
            await self._session.execute(self._playable().where(Song.id == song_id))
        ).first()
        return None if row is None else PlayableSong(song=row[0], line_count=row[1])

    async def get_current_lines(
        self, song_id: uuid.UUID
    ) -> CurrentAnalysisLines | None:
        """Fetch only the lyric lines of a song's current analysis.

        The pitch curve (the bulk of the JSONB document) is not loaded.

        Args:
            song_id: Id of the song.

        Returns:
            The lines with the analysis identity, or None if there is none.
        """
        row = (
            await self._session.execute(
                select(
                    SongAnalysis.id,
                    SongAnalysis.version,
                    SongAnalysis.format_version,
                    SongAnalysis.data["lines"],
                ).where(SongAnalysis.song_id == song_id, SongAnalysis.is_current)
            )
        ).first()
        if row is None:
            return None
        analysis_id, version, format_version, lines = row
        return CurrentAnalysisLines(
            analysis_id=analysis_id,
            version=version,
            format_version=format_version,
            lines=lines,
        )

    async def get_current_pitch(
        self, song_id: uuid.UUID
    ) -> tuple[uuid.UUID, dict[str, Any], list[dict[str, Any]]] | None:
        """Fetch the pitch curve and lines of a song's current analysis.

        Args:
            song_id: Id of the song.

        Returns:
            The analysis id, the raw ``pitch`` value and the raw ``lines``
            value, or None if the song has no current analysis.
        """
        row = (
            await self._session.execute(
                select(
                    SongAnalysis.id,
                    SongAnalysis.data["pitch"],
                    SongAnalysis.data["lines"],
                ).where(SongAnalysis.song_id == song_id, SongAnalysis.is_current)
            )
        ).first()
        if row is None:
            return None
        analysis_id, pitch, lines = row
        return analysis_id, pitch, lines
