import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionJob, SongAnalysis, SongAsset
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.domain.enums import (
    AssetKind,
    IngestionStage,
    PlaySessionStatus,
    SongStatus,
)

pytestmark = pytest.mark.integration


async def _count(
    session: AsyncSession,
    model: type[SongAsset] | type[SongAnalysis] | type[IngestionJob],
    song_id: uuid.UUID,
) -> int:
    result = await session.scalar(select(func.count()).where(model.song_id == song_id))
    return int(result or 0)


# --- Songs -------------------------------------------------------------------


async def test_add_song_defaults_to_pending(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Bohemian Rhapsody", "Queen", "en")

    assert isinstance(song.id, uuid.UUID)
    assert song.status is SongStatus.PENDING
    assert song.created_at is not None
    assert song.language == "en"


async def test_get_missing_song_returns_none(db_session: AsyncSession) -> None:
    assert await SongRepository(db_session).get(uuid.uuid4()) is None


async def test_set_status_updates_song(db_session: AsyncSession) -> None:
    repo = SongRepository(db_session)
    song = await repo.add("Song", "Artist")

    updated = await repo.set_status(song.id, SongStatus.FAILED, "demucs crashed")

    assert updated is True
    fetched = await repo.get(song.id)
    assert fetched is not None
    assert fetched.status is SongStatus.FAILED
    assert fetched.error_message == "demucs crashed"


async def test_set_status_on_missing_song_returns_false(
    db_session: AsyncSession,
) -> None:
    updated = await SongRepository(db_session).set_status(
        uuid.uuid4(), SongStatus.READY
    )

    assert updated is False


async def test_list_by_status_filters_and_paginates(db_session: AsyncSession) -> None:
    repo = SongRepository(db_session)
    first = await repo.add("A", "Artist")
    second = await repo.add("B", "Artist")
    other = await repo.add("C", "Artist")
    await repo.set_status(other.id, SongStatus.READY)

    pending = await repo.list_by_status(SongStatus.PENDING)
    page = await repo.list_by_status(SongStatus.PENDING, limit=1, offset=1)

    assert {s.id for s in pending} == {first.id, second.id}
    assert len(page) == 1


# --- Analyses ----------------------------------------------------------------


async def test_add_version_increments_and_switches_current(
    db_session: AsyncSession,
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    repo = SongAnalysisRepository(db_session)

    v1 = await repo.add_version(song.id, format_version=1, data={"lines": []})
    v2 = await repo.add_version(song.id, format_version=1, data={"lines": [1]})

    assert (v1.version, v2.version) == (1, 2)
    current = await repo.get_current(song.id)
    assert current is not None
    assert current.id == v2.id
    # The already-loaded v1 instance must be in sync without a refresh.
    assert v1.is_current is False


async def test_get_current_without_analysis_returns_none(
    db_session: AsyncSession,
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")

    assert await SongAnalysisRepository(db_session).get_current(song.id) is None


async def test_only_one_current_analysis_per_song(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    for version in (1, 2):
        db_session.add(
            SongAnalysis(
                song_id=song.id,
                version=version,
                is_current=True,
                format_version=1,
                data={},
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


# --- Ingestion jobs ----------------------------------------------------------


async def test_job_stage_transitions_record_timestamps(
    db_session: AsyncSession,
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    repo = IngestionJobRepository(db_session)
    job = await repo.add(song.id)
    assert job.stage is IngestionStage.QUEUED
    assert job.started_at is None

    await repo.set_stage(job, IngestionStage.SEPARATING)
    started_at = job.started_at
    assert started_at is not None
    assert job.finished_at is None

    await repo.set_stage(job, IngestionStage.TRANSCRIBING)
    assert job.started_at == started_at

    await repo.set_stage(job, IngestionStage.FAILED, error_message="whisper OOM")
    assert job.finished_at is not None
    assert job.error_message == "whisper OOM"


async def test_get_latest_job_for_song(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    repo = IngestionJobRepository(db_session)
    assert await repo.get_latest_for_song(song.id) is None

    for _ in range(3):
        await repo.add(song.id)
    latest = await repo.add(song.id)

    found = await repo.get_latest_for_song(song.id)
    assert found is not None
    assert found.id == latest.id


# --- Play sessions -----------------------------------------------------------


async def test_play_session_takes_song_from_analysis(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analysis = await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    repo = PlaySessionRepository(db_session)

    play = await repo.add(analysis, player_name="Ana", latency_offset_ms=120)

    fetched = await repo.get(play.id)
    assert fetched is not None
    assert fetched.song_id == song.id
    assert fetched.analysis_id == analysis.id
    assert fetched.status is PlaySessionStatus.ACTIVE
    assert fetched.latency_offset_ms == 120


async def test_line_scores_are_listed_by_line(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analysis = await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    repo = PlaySessionRepository(db_session)
    play = await repo.add(analysis, player_name="Ana")

    await repo.add_line_score(play.id, 1, score=80.0, accuracy=0.8, hit=True)
    await repo.add_line_score(play.id, 0, score=40.0, accuracy=0.4, hit=False)

    scores = await repo.list_line_scores(play.id)
    assert [s.line_index for s in scores] == [0, 1]


async def test_line_cannot_be_scored_twice(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analysis = await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    repo = PlaySessionRepository(db_session)
    play = await repo.add(analysis, player_name="Ana")
    await repo.add_line_score(play.id, 0, score=50.0, accuracy=0.5, hit=True)

    with pytest.raises(IntegrityError):
        await repo.add_line_score(play.id, 0, score=60.0, accuracy=0.6, hit=True)


async def test_score_out_of_range_is_rejected(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analysis = await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    repo = PlaySessionRepository(db_session)
    play = await repo.add(analysis, player_name="Ana")

    with pytest.raises(IntegrityError):
        await repo.add_line_score(play.id, 0, score=101.0, accuracy=0.5, hit=True)


# --- Deletion rules ----------------------------------------------------------


async def test_deleting_song_cascades_to_children(db_session: AsyncSession) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    await IngestionJobRepository(db_session).add(song.id)
    db_session.add(
        SongAsset(
            song_id=song.id,
            kind=AssetKind.ORIGINAL,
            storage_key=f"songs/{song.id}/original.mp3",
            content_type="audio/mpeg",
            size_bytes=1234,
        )
    )
    await db_session.flush()

    await db_session.delete(song)
    await db_session.flush()

    for model in (SongAsset, SongAnalysis, IngestionJob):
        assert await _count(db_session, model, song.id) == 0


async def test_song_with_play_sessions_cannot_be_deleted(
    db_session: AsyncSession,
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analysis = await SongAnalysisRepository(db_session).add_version(song.id, 1, {})
    await PlaySessionRepository(db_session).add(analysis, player_name="Ana")

    await db_session.delete(song)
    with pytest.raises(IntegrityError):
        await db_session.flush()
