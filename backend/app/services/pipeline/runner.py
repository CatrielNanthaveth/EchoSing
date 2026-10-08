"""Orchestration of the ingestion stages for one job."""

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import IngestionJob
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.songs import SongRepository
from app.db.session import create_engine, create_session_factory
from app.domain.enums import IngestionStage, SongStatus
from app.services.pipeline.errors import StageError
from app.services.pipeline.persist import PersistStage
from app.services.pipeline.pitch import build_pitch_stage
from app.services.pipeline.segmentation import SegmentationStage
from app.services.pipeline.separation import build_separation_stage
from app.services.pipeline.transcription import build_transcription_stage
from app.storage.base import StorageBackend
from app.storage.local import LocalStorage

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 2000

StageRunner = Callable[[uuid.UUID], Awaitable[object]]


class PipelineOutcome(BaseModel):
    """Result of running the pipeline for a job.

    Attributes:
        job_id: Id of the job.
        song_id: Id of the song.
        stage: Final stage of the job (``done`` or ``failed``).
        error: Failure reason, if the job failed.
        skipped: True if the job had already finished and was not run.
    """

    job_id: uuid.UUID
    song_id: uuid.UUID
    stage: IngestionStage
    error: str | None = None
    skipped: bool = False


class IngestionPipeline:
    """Runs the ingestion stages of a job in order and tracks its state.

    The job stage is updated before each stage, so progress is visible. A
    failure marks both the job and the song as failed with the stage and the
    error; failures are deterministic, so nothing is retried automatically.
    Jobs that already finished (done or failed) are skipped, which makes
    redelivered Celery messages harmless; interrupted jobs start over, which
    is safe because every stage overwrites its outputs.
    """

    def __init__(
        self,
        session: AsyncSession,
        stages: Sequence[tuple[IngestionStage, StageRunner]],
    ) -> None:
        """Initialize the pipeline.

        Args:
            session: Database session used for job and song states.
            stages: Stages to run in order, with the job stage they report.
        """
        self._session = session
        self._stages = stages
        self._songs = SongRepository(session)
        self._jobs = IngestionJobRepository(session)

    async def run(self, job_id: uuid.UUID) -> PipelineOutcome:
        """Run every stage for a job.

        Args:
            job_id: Id of the ingestion job.

        Returns:
            How the job ended.

        Raises:
            StageError: If the job does not exist.
        """
        job = await self._session.get(IngestionJob, job_id)
        if job is None:
            raise StageError(f"Ingestion job {job_id} does not exist")
        song_id = job.song_id
        if job.stage.is_terminal:
            logger.info("Job %s already %s; skipping", job_id, job.stage.value)
            return PipelineOutcome(
                job_id=job_id, song_id=song_id, stage=job.stage, skipped=True
            )

        await self._songs.set_status(song_id, SongStatus.PROCESSING)
        await self._session.commit()

        for stage, runner in self._stages:
            await self._jobs.set_stage(job, stage)
            await self._session.commit()
            logger.info("Job %s: %s", job_id, stage.value)
            try:
                await runner(song_id)
            except Exception as error:
                logger.exception("Job %s failed while %s", job_id, stage.value)
                message = f"{stage.value}: {error}"[:MAX_ERROR_CHARS]
                await self._fail(job, song_id, message)
                return PipelineOutcome(
                    job_id=job_id,
                    song_id=song_id,
                    stage=IngestionStage.FAILED,
                    error=message,
                )

        await self._jobs.set_stage(job, IngestionStage.DONE)
        await self._songs.set_status(song_id, SongStatus.READY)
        await self._session.commit()
        return PipelineOutcome(
            job_id=job_id, song_id=song_id, stage=IngestionStage.DONE
        )

    async def _fail(self, job: IngestionJob, song_id: uuid.UUID, message: str) -> None:
        """Persist the failure of a job and its song."""
        await self._session.rollback()
        # The rollback expired the job instance: reload it before writing.
        await self._session.refresh(job)
        await self._jobs.set_stage(job, IngestionStage.FAILED, error_message=message)
        await self._songs.set_status(song_id, SongStatus.FAILED, message)
        await self._session.commit()


def build_pipeline(
    session: AsyncSession, storage: StorageBackend, settings: Settings
) -> IngestionPipeline:
    """Create the full ingestion pipeline from the settings.

    Order: separate -> transcribe -> pitch -> segment -> persist. Pitch runs
    before segment so lines are built from the hallucination-filtered
    transcription.

    Args:
        session: Database session.
        storage: Storage backend.
        settings: Application settings.

    Returns:
        The pipeline.
    """
    return IngestionPipeline(
        session,
        [
            (
                IngestionStage.SEPARATING,
                build_separation_stage(session, storage, settings).run,
            ),
            (
                IngestionStage.TRANSCRIBING,
                build_transcription_stage(session, storage, settings).run,
            ),
            (
                IngestionStage.EXTRACTING_PITCH,
                build_pitch_stage(session, storage, settings).run,
            ),
            (IngestionStage.SEGMENTING, SegmentationStage(session, storage).run),
            (IngestionStage.PERSISTING, PersistStage(session, storage).run),
        ],
    )


async def run_job(job_id: uuid.UUID, settings: Settings) -> PipelineOutcome:
    """Run a job with its own database engine (for workers and the CLI).

    Args:
        job_id: Id of the ingestion job.
        settings: Application settings.

    Returns:
        How the job ended.
    """
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            storage = LocalStorage(settings.storage_root)
            return await build_pipeline(session, storage, settings).run(job_id)
    finally:
        await engine.dispose()
