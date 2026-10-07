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
from app.db.session import get_db_session
from app.domain.enums import SeparationPreset, SongStatus
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
