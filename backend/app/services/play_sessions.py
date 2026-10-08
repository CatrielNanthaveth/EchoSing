"""Karaoke play sessions: start, score lines, finish and report."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.catalog import CatalogRepository
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.repositories.songs import SongAnalysisRepository
from app.db.session import get_db_session
from app.schemas.sessions import SessionCreate, SessionCreated
from app.services.errors import SongNotFoundError


class PlaySessionService:
    """Manages the lifecycle of play sessions."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: Database session; this service commits its own changes.
        """
        self._session = session
        self._catalog = CatalogRepository(session)
        self._analyses = SongAnalysisRepository(session)
        self._play_sessions = PlaySessionRepository(session)

    async def create(self, request: SessionCreate) -> SessionCreated:
        """Start a play session on the current analysis of a playable song.

        Args:
            request: Song, player name and measured latency.

        Returns:
            The session and what will be sung.

        Raises:
            SongNotFoundError: If the song does not exist or is not playable.
        """
        playable = await self._catalog.get_playable(request.song_id)
        identity = await self._analyses.get_current_identity(request.song_id)
        if playable is None or identity is None:
            raise SongNotFoundError(f"Song {request.song_id} is not available")
        analysis_id, version = identity

        play_session = await self._play_sessions.start(
            request.song_id,
            analysis_id,
            request.player_name,
            request.latency_offset_ms,
        )
        await self._session.commit()
        return SessionCreated(
            session_id=play_session.id,
            song_id=request.song_id,
            analysis_id=analysis_id,
            analysis_version=version,
            line_count=playable.line_count,
            player_name=play_session.player_name,
            latency_offset_ms=play_session.latency_offset_ms,
        )


def get_play_session_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlaySessionService:
    """Provide a ``PlaySessionService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return PlaySessionService(session)
