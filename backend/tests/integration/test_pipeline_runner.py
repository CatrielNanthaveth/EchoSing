import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import IngestionJob, Song
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import IngestionStage, SongStatus
from app.services.pipeline.errors import StageError
from app.services.pipeline.runner import (
    IngestionPipeline,
    StageRunner,
    build_pipeline,
)
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

STAGES = [
    IngestionStage.SEPARATING,
    IngestionStage.TRANSCRIBING,
    IngestionStage.EXTRACTING_PITCH,
    IngestionStage.SEGMENTING,
    IngestionStage.PERSISTING,
]


class Recorder:
    """Fake stages that record which ran and what the job stage was then."""

    def __init__(
        self, session: AsyncSession, fail_at: IngestionStage | None = None
    ) -> None:
        self.session = session
        self.fail_at = fail_at
        self.ran: list[tuple[IngestionStage, IngestionStage, SongStatus]] = []

    def stage(self, stage: IngestionStage) -> StageRunner:
        async def run(song_id: uuid.UUID) -> None:
            job_stage = await self.session.scalar(
                select(IngestionJob.stage).where(IngestionJob.song_id == song_id)
            )
            song = await self.session.get(Song, song_id)
            assert song is not None and job_stage is not None
            self.ran.append((stage, job_stage, song.status))
            if stage is self.fail_at:
                raise RuntimeError("CUDA out of memory")

        return run

    def pipeline(self) -> IngestionPipeline:
        return IngestionPipeline(self.session, [(s, self.stage(s)) for s in STAGES])


async def _job(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    song = await SongRepository(session).add("Song", "Artist")
    job = await IngestionJobRepository(session).add(song.id)
    await session.commit()
    return song.id, job.id


async def test_runs_every_stage_in_order_and_finishes_ready(
    db_session: AsyncSession,
) -> None:
    song_id, job_id = await _job(db_session)
    recorder = Recorder(db_session)

    outcome = await recorder.pipeline().run(job_id)

    assert outcome.stage is IngestionStage.DONE
    assert outcome.error is None
    # Each stage saw the job in its own stage and the song processing.
    assert recorder.ran == [(s, s, SongStatus.PROCESSING) for s in STAGES]
    job = await db_session.get(IngestionJob, job_id)
    song = await db_session.get(Song, song_id)
    assert job is not None and song is not None
    assert job.stage is IngestionStage.DONE
    assert job.started_at is not None and job.finished_at is not None
    assert song.status is SongStatus.READY


async def test_failing_stage_stops_the_pipeline_and_records_why(
    db_session: AsyncSession,
) -> None:
    song_id, job_id = await _job(db_session)
    recorder = Recorder(db_session, fail_at=IngestionStage.TRANSCRIBING)

    outcome = await recorder.pipeline().run(job_id)

    assert outcome.stage is IngestionStage.FAILED
    assert outcome.error == "transcribing: CUDA out of memory"
    assert [stage for stage, _, _ in recorder.ran] == STAGES[:2]
    job = await db_session.get(IngestionJob, job_id)
    song = await db_session.get(Song, song_id)
    assert job is not None and song is not None
    assert job.stage is IngestionStage.FAILED
    assert job.error_message == "transcribing: CUDA out of memory"
    assert job.finished_at is not None
    assert song.status is SongStatus.FAILED
    assert song.error_message == "transcribing: CUDA out of memory"


@pytest.mark.parametrize("final", [IngestionStage.DONE, IngestionStage.FAILED])
async def test_finished_jobs_are_skipped(
    db_session: AsyncSession, final: IngestionStage
) -> None:
    _, job_id = await _job(db_session)
    job = await db_session.get(IngestionJob, job_id)
    assert job is not None
    await IngestionJobRepository(db_session).set_stage(job, final)
    await db_session.commit()
    recorder = Recorder(db_session)

    outcome = await recorder.pipeline().run(job_id)

    assert outcome.skipped is True
    assert outcome.stage is final
    assert recorder.ran == []


async def test_interrupted_job_starts_over(db_session: AsyncSession) -> None:
    _, job_id = await _job(db_session)
    job = await db_session.get(IngestionJob, job_id)
    assert job is not None
    await IngestionJobRepository(db_session).set_stage(job, IngestionStage.SEGMENTING)
    await db_session.commit()
    recorder = Recorder(db_session)

    outcome = await recorder.pipeline().run(job_id)

    assert outcome.stage is IngestionStage.DONE
    assert len(recorder.ran) == len(STAGES)


async def test_unknown_job_raises(db_session: AsyncSession) -> None:
    with pytest.raises(StageError, match="does not exist"):
        await Recorder(db_session).pipeline().run(uuid.uuid4())


def test_build_pipeline_wires_stages_in_order(tmp_path: Path) -> None:
    pipeline = build_pipeline(None, LocalStorage(tmp_path), Settings(_env_file=None))  # type: ignore[arg-type]

    assert [stage for stage, _ in pipeline._stages] == STAGES
