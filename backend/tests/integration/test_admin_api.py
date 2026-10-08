import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Song
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.db.session import get_db_session
from app.domain.enums import IngestionStage, SeparationPreset, SongStatus
from app.main import create_app
from app.storage.dependencies import get_storage
from app.storage.local import LocalStorage
from app.workers.queue import get_job_queue
from tests.fakes import FakeJobQueue

pytestmark = pytest.mark.integration

TOKEN = "test-admin-token"
HEADERS = {"X-Admin-Token": TOKEN}
FORM = {"title": "Bohemian Rhapsody", "artist": "Queen", "language": "en"}


def _file(name: str = "song.mp3", content: bytes = b"fake-audio") -> dict[str, Any]:
    return {"file": (name, content, "audio/mpeg")}


@pytest.fixture
def queue() -> FakeJobQueue:
    return FakeJobQueue()


def _admin_app(
    settings: Settings,
    db_session: AsyncSession,
    queue: FakeJobQueue,
    storage_root: Path,
) -> FastAPI:
    app = create_app(settings)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_storage] = lambda: LocalStorage(storage_root)
    app.dependency_overrides[get_job_queue] = lambda: queue
    return app


@pytest.fixture
async def admin_client(
    db_session: AsyncSession, queue: FakeJobQueue, tmp_path: Path
) -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None, admin_token=TOKEN, max_upload_bytes=1024)
    app = _admin_app(settings, db_session, queue, tmp_path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_upload_song_returns_202(
    admin_client: AsyncClient, db_session: AsyncSession, queue: FakeJobQueue
) -> None:
    response = await admin_client.post(
        "/admin/songs", data=FORM, files=_file(), headers=HEADERS
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["stage"] == "queued"
    assert queue.enqueued and str(queue.enqueued[0]) == body["job_id"]
    song = await db_session.scalar(select(Song))
    assert song is not None
    assert str(song.id) == body["song_id"]


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
async def test_upload_requires_valid_token(
    admin_client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await admin_client.post(
        "/admin/songs", data=FORM, files=_file(), headers=headers
    )

    assert response.status_code == 401


async def test_admin_endpoints_disabled_without_configured_token(
    db_session: AsyncSession, queue: FakeJobQueue, tmp_path: Path
) -> None:
    app = _admin_app(Settings(_env_file=None), db_session, queue, tmp_path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/admin/songs", data=FORM, files=_file(), headers=HEADERS
        )

    assert response.status_code == 503
    assert queue.enqueued == []


async def test_unsupported_file_returns_415(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/admin/songs", data=FORM, files=_file("notes.txt"), headers=HEADERS
    )

    assert response.status_code == 415


async def test_too_large_file_returns_413(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(
        "/admin/songs", data=FORM, files=_file(content=b"x" * 2048), headers=HEADERS
    )

    assert response.status_code == 413
    assert await db_session.scalar(select(Song)) is None


@pytest.mark.parametrize(
    "form",
    [
        {**FORM, "title": "   "},
        {**FORM, "artist": ""},
        {**FORM, "language": "spanish"},
        {"artist": "Queen"},
    ],
)
async def test_invalid_metadata_returns_422(
    admin_client: AsyncClient, form: dict[str, str]
) -> None:
    response = await admin_client.post(
        "/admin/songs", data=form, files=_file(), headers=HEADERS
    )

    assert response.status_code == 422


async def test_missing_file_returns_422(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/admin/songs", data=FORM, headers=HEADERS)

    assert response.status_code == 422


async def test_empty_language_is_treated_as_unknown(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(
        "/admin/songs", data={**FORM, "language": ""}, files=_file(), headers=HEADERS
    )

    assert response.status_code == 202
    song = await db_session.scalar(select(Song))
    assert song is not None
    assert song.language is None


async def test_queue_outage_returns_503_and_marks_song_failed(
    admin_client: AsyncClient, db_session: AsyncSession, queue: FakeJobQueue
) -> None:
    queue.fail = True

    response = await admin_client.post(
        "/admin/songs", data=FORM, files=_file(), headers=HEADERS
    )

    assert response.status_code == 503
    song = await db_session.scalar(select(Song))
    assert song is not None
    assert song.status is SongStatus.FAILED


async def test_upload_with_roformer_preset(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(
        "/admin/songs",
        data={**FORM, "separation_preset": "roformer"},
        files=_file(),
        headers=HEADERS,
    )

    assert response.status_code == 202
    assert response.json()["separation_preset"] == "roformer"
    song = await db_session.scalar(select(Song))
    assert song is not None
    assert song.separation_preset is SeparationPreset.ROFORMER


@pytest.mark.parametrize("value", ["", None])
async def test_missing_preset_uses_server_default(
    admin_client: AsyncClient, value: str | None
) -> None:
    form = {**FORM} if value is None else {**FORM, "separation_preset": value}

    response = await admin_client.post(
        "/admin/songs", data=form, files=_file(), headers=HEADERS
    )

    assert response.status_code == 202
    assert response.json()["separation_preset"] == "demucs"


async def test_unknown_preset_returns_422(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/admin/songs",
        data={**FORM, "separation_preset": "spleeter"},
        files=_file(),
        headers=HEADERS,
    )

    assert response.status_code == 422


# --- official lyrics -----------------------------------------------------------


async def test_upload_with_lyrics_stores_them(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await admin_client.post(
        "/admin/songs",
        data={**FORM, "lyrics": "Dame de tu vida\nY de tu tiempo"},
        files=_file(),
        headers=HEADERS,
    )

    assert response.status_code == 202
    song = await db_session.scalar(select(Song))
    assert song is not None
    assert song.lyrics_text == "Dame de tu vida\nY de tu tiempo"


async def test_put_lyrics_sets_them(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")

    response = await admin_client.put(
        f"/admin/songs/{song.id}/lyrics",
        json={"lyrics": "[Coro]\nDame de tu vida\n\nY de tu tiempo\n(uh uh)"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"song_id": str(song.id), "lines": 2}
    await db_session.refresh(song)
    assert song.lyrics_text is not None
    assert song.lyrics_text.startswith("[Coro]")


async def test_put_lyrics_unknown_song_returns_404(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        f"/admin/songs/{uuid.uuid4()}/lyrics",
        json={"lyrics": "Dame de tu vida"},
        headers=HEADERS,
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"lyrics": ""}, {"lyrics": "[Coro]\n\n(uh uh)"}, {}, {"lyrics": "x" * 20_001}],
)
async def test_put_invalid_lyrics_returns_422(
    admin_client: AsyncClient, db_session: AsyncSession, body: dict[str, str]
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")

    response = await admin_client.put(
        f"/admin/songs/{song.id}/lyrics", json=body, headers=HEADERS
    )

    assert response.status_code == 422


async def test_put_lyrics_requires_token(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        f"/admin/songs/{uuid.uuid4()}/lyrics", json={"lyrics": "Dame"}
    )

    assert response.status_code == 401


# --- ingestion status ------------------------------------------------------------


async def test_status_of_a_song_with_its_latest_job(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    await SongRepository(db_session).set_lyrics(song.id, "Dame de tu vida")
    jobs = IngestionJobRepository(db_session)
    await jobs.add(song.id)
    latest = await jobs.add(song.id)
    await jobs.set_stage(latest, IngestionStage.FAILED, error_message="pitch: boom")
    await db_session.commit()

    response = await admin_client.get(f"/admin/songs/{song.id}/status", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["separation_preset"] == "demucs"
    assert body["has_lyrics"] is True
    assert body["current_analysis_version"] is None
    assert body["latest_job"]["id"] == str(latest.id)
    assert body["latest_job"]["stage"] == "failed"
    assert body["latest_job"]["error_message"] == "pitch: boom"
    assert body["latest_job"]["finished_at"] is not None


async def test_status_reports_the_current_analysis_version(
    admin_client: AsyncClient, db_session: AsyncSession, analysis_json: dict[str, Any]
) -> None:
    song = await SongRepository(db_session).add("Song", "Artist")
    analyses = SongAnalysisRepository(db_session)
    await analyses.add_version(song.id, 1, analysis_json)
    await analyses.add_version(song.id, 1, analysis_json)
    await db_session.commit()

    body = (
        await admin_client.get(f"/admin/songs/{song.id}/status", headers=HEADERS)
    ).json()

    assert body["current_analysis_version"] == 2
    assert body["latest_job"] is None
    assert body["has_lyrics"] is False


async def test_status_errors(admin_client: AsyncClient) -> None:
    unknown = f"/admin/songs/{uuid.uuid4()}/status"

    assert (await admin_client.get(unknown, headers=HEADERS)).status_code == 404
    assert (await admin_client.get(unknown)).status_code == 401
