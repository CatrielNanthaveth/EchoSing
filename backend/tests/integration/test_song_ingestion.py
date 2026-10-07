from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import register_file
from app.db.models import IngestionJob, Song, SongAsset
from app.domain.enums import AssetKind, IngestionStage, SongStatus
from app.services.song_ingestion import (
    NewSong,
    SongIngestionService,
    UnsupportedAudioFormatError,
    UploadTooLargeError,
)
from app.storage.local import LocalStorage
from app.workers.queue import QueueUnavailableError
from tests.fakes import FakeJobQueue

pytestmark = pytest.mark.integration

MAX_BYTES = 1024
SONG = NewSong(title="  Bohemian Rhapsody ", artist="Queen", language="en")


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def queue() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture
def service(
    db_session: AsyncSession, storage: LocalStorage, queue: FakeJobQueue
) -> SongIngestionService:
    return SongIngestionService(db_session, storage, queue, MAX_BYTES)


async def _count(session: AsyncSession, model: type[Song] | type[SongAsset]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _stored_files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "storage").rglob("*") if p.is_file()]


async def test_register_song_persists_and_queues(
    service: SongIngestionService,
    db_session: AsyncSession,
    storage: LocalStorage,
    queue: FakeJobQueue,
) -> None:
    result = await service.register_song(
        SONG, "Queen - Bohemian.MP3", chunks(b"ab", b"c")
    )

    assert result.status is SongStatus.PENDING
    assert result.stage is IngestionStage.QUEUED
    assert queue.enqueued == [result.job_id]

    song = await db_session.get(Song, result.song_id)
    assert song is not None
    assert (song.title, song.artist, song.language) == (
        "Bohemian Rhapsody",
        "Queen",
        "en",
    )

    asset = await db_session.scalar(
        select(SongAsset).where(SongAsset.song_id == result.song_id)
    )
    assert asset is not None
    assert asset.kind is AssetKind.ORIGINAL
    assert asset.storage_key == f"songs/{result.song_id}/original.mp3"
    assert asset.content_type == "audio/mpeg"
    assert asset.size_bytes == 3
    assert (
        b"".join([c async for c in await storage.stream(asset.storage_key)]) == b"abc"
    )

    job = await db_session.get(IngestionJob, result.job_id)
    assert job is not None
    assert job.task_id == f"task-{result.job_id}"


async def test_unsupported_extension_leaves_nothing(
    service: SongIngestionService,
    db_session: AsyncSession,
    queue: FakeJobQueue,
    tmp_path: Path,
) -> None:
    with pytest.raises(UnsupportedAudioFormatError):
        await service.register_song(SONG, "lyrics.txt", chunks(b"x"))

    assert await _count(db_session, Song) == 0
    assert _stored_files(tmp_path) == []
    assert queue.enqueued == []


async def test_too_large_upload_leaves_nothing(
    service: SongIngestionService,
    db_session: AsyncSession,
    queue: FakeJobQueue,
    tmp_path: Path,
) -> None:
    with pytest.raises(UploadTooLargeError):
        await service.register_song(
            SONG, "song.mp3", chunks(b"x" * 1000, b"x" * (MAX_BYTES - 999))
        )

    assert await _count(db_session, Song) == 0
    assert await _count(db_session, SongAsset) == 0
    assert _stored_files(tmp_path) == []
    assert queue.enqueued == []


async def test_upload_of_exactly_max_size_is_accepted(
    service: SongIngestionService,
) -> None:
    result = await service.register_song(SONG, "song.wav", chunks(b"x" * MAX_BYTES))

    assert result.status is SongStatus.PENDING


async def test_queue_failure_marks_song_and_job_failed(
    db_session: AsyncSession, storage: LocalStorage, tmp_path: Path
) -> None:
    service = SongIngestionService(
        db_session, storage, FakeJobQueue(fail=True), MAX_BYTES
    )

    with pytest.raises(QueueUnavailableError):
        await service.register_song(SONG, "song.flac", chunks(b"audio"))

    song = await db_session.scalar(select(Song))
    assert song is not None
    assert song.status is SongStatus.FAILED
    assert song.error_message == "broker is down"
    job = await db_session.scalar(select(IngestionJob))
    assert job is not None
    assert job.stage is IngestionStage.FAILED
    assert job.finished_at is not None
    assert job.task_id is None
    # The original file is kept so the song can be re-queued later.
    assert len(_stored_files(tmp_path)) == 1


async def test_cli_register_file_streams_local_file(
    service: SongIngestionService, storage: LocalStorage, tmp_path: Path
) -> None:
    source = tmp_path / "track.ogg"
    source.write_bytes(b"ogg-bytes")

    result = await register_file(service, source, SONG)

    key = f"songs/{result.song_id}/original.ogg"
    assert b"".join([c async for c in await storage.stream(key)]) == b"ogg-bytes"
