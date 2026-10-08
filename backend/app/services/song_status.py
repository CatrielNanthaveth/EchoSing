"""Ingestion status reports for administrators."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.db.session import get_db_session
from app.schemas.catalog import JobReport, SongStatusReport
from app.services.errors import SongNotFoundError


class SongStatusService:
    """Reports where a song is in the ingestion pipeline."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: Database session.
        """
        self._songs = SongRepository(session)
        self._jobs = IngestionJobRepository(session)
        self._analyses = SongAnalysisRepository(session)

    async def get_status(self, song_id: uuid.UUID) -> SongStatusReport:
        """Report the status of a song and of its latest ingestion job.

        Args:
            song_id: Id of the song.

        Returns:
            The status report.

        Raises:
            SongNotFoundError: If the song does not exist.
        """
        song = await self._songs.get(song_id)
        if song is None:
            raise SongNotFoundError(f"Song {song_id} does not exist")
        job = await self._jobs.get_latest_for_song(song_id)
        return SongStatusReport(
            song_id=song.id,
            title=song.title,
            artist=song.artist,
            status=song.status,
            error_message=song.error_message,
            separation_preset=song.separation_preset,
            has_lyrics=bool(song.lyrics_text),
            duration_ms=song.duration_ms,
            current_analysis_version=await self._analyses.get_current_version(song_id),
            latest_job=None
            if job is None
            else JobReport(
                id=job.id,
                stage=job.stage,
                task_id=job.task_id,
                error_message=job.error_message,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
            ),
        )


def get_song_status_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SongStatusService:
    """Provide a ``SongStatusService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return SongStatusService(session)
