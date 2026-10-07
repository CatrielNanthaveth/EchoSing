"""Persistence of ingestion jobs."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionJob
from app.domain.enums import IngestionStage


class IngestionJobRepository:
    """Data access for ``IngestionJob`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    async def add(self, song_id: uuid.UUID) -> IngestionJob:
        """Create a job in ``QUEUED`` stage.

        Args:
            song_id: Id of the song to ingest.

        Returns:
            The persisted job.
        """
        job = IngestionJob(song_id=song_id)
        self._session.add(job)
        await self._session.flush()
        return job

    async def get_latest_for_song(self, song_id: uuid.UUID) -> IngestionJob | None:
        """Fetch the most recent job of a song.

        Args:
            song_id: Id of the song.

        Returns:
            The newest job, or None if the song was never queued.
        """
        return await self._session.scalar(
            select(IngestionJob)
            .where(IngestionJob.song_id == song_id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(1)
        )

    async def set_stage(
        self,
        job: IngestionJob,
        stage: IngestionStage,
        *,
        error_message: str | None = None,
    ) -> None:
        """Move a job to a new stage, recording start and finish times.

        ``started_at`` is set the first time the job leaves ``QUEUED`` and
        ``finished_at`` when it reaches a terminal stage.

        Args:
            job: Job to update.
            stage: New stage.
            error_message: Failure reason, stored when given.
        """
        now = datetime.now(UTC)
        job.stage = stage
        if stage is not IngestionStage.QUEUED and job.started_at is None:
            job.started_at = now
        if stage.is_terminal:
            job.finished_at = now
        if error_message is not None:
            job.error_message = error_message
        await self._session.flush()
