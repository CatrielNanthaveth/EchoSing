import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.session import get_db_session
from app.main import create_app
from app.storage.dependencies import get_storage
from app.storage.local import LocalStorage
from tests.integration.catalog_helpers import add_song
from tests.integration.test_session_socket import (
    HOP_MS,
    connect,
    open_client,
    pitch_message,
    receive,
    start_session,
    sung_line,
)

pytestmark = pytest.mark.integration

TOKEN = "admin-secret"
ADMIN = {"X-Admin-Token": TOKEN}


@pytest.fixture
def app(db_session: AsyncSession, storage: LocalStorage) -> FastAPI:
    application = create_app(Settings(_env_file=None, admin_token=TOKEN))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = session_override
    application.dependency_overrides[get_storage] = lambda: storage
    return application


@pytest.fixture
async def song_id(
    db_session: AsyncSession, storage: LocalStorage, analysis_json: dict[str, Any]
) -> uuid.UUID:
    return await add_song(db_session, storage, analysis_json, "Song")


async def sing(
    client: AsyncClient,
    song_id: uuid.UUID,
    analysis: dict[str, Any],
    lines: dict[int, float],
    latency_ms: int = 0,
) -> str:
    """Sing some lines (index -> semitones off) and return the session id."""
    session_id = await start_session(client, song_id, latency_ms=latency_ms)
    async with connect(client, session_id) as ws:
        await receive(ws)
        for index, semitones in lines.items():
            delay = latency_ms // HOP_MS
            await ws.send_text(
                pitch_message(
                    index,
                    sung_line(analysis, index, semitones=semitones, delay_frames=delay),
                )
            )
            await receive(ws)
    return session_id


# --- practice (public) ---------------------------------------------------------------


async def test_analysis_of_a_sung_line(
    app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await sing(client, song_id, analysis_json, {0: 0.0, 1: -1.0})
        perfect = (await client.get(f"/sessions/{session_id}/lines/0/analysis")).json()
        flat = (await client.get(f"/sessions/{session_id}/lines/1/analysis")).json()

    assert perfect["status"] == "analyzed"
    assert (perfect["line_index"], perfect["text"]) == (0, "Hello darkness, my")
    assert (perfect["start_ms"], perfect["end_ms"]) == (200, 900)
    assert perfect["difficulty"] == "hard"
    assert perfect["words"][0] == {"text": "Hello", "start_ms": 0, "end_ms": 250}
    analysis = perfect["analysis"]
    assert analysis["result"]["score"] == 100.0
    assert analysis["timing_offset_ms"] == 0.0
    assert analysis["pitch_offset_semitones"] == 0.0
    assert analysis["sung_midi"] == analysis["reference_midi"]
    assert flat["analysis"]["pitch_offset_semitones"] == -1.0
    assert flat["analysis"]["result"]["score"] == pytest.approx(66.67, abs=0.01)


async def test_analysis_undoes_the_session_latency(
    app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await sing(
            client, song_id, analysis_json, {0: 0.0}, latency_ms=120
        )
        body = (await client.get(f"/sessions/{session_id}/lines/0/analysis")).json()

    assert body["analysis"]["timing_offset_ms"] == 0.0
    assert body["analysis"]["result"]["score"] == 100.0


async def test_unsung_line_has_no_analysis(
    app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await sing(client, song_id, analysis_json, {0: 0.0})
        body = (await client.get(f"/sessions/{session_id}/lines/2/analysis")).json()

    assert (body["status"], body["analysis"]) == ("not_sung", None)
    assert [word["text"] for word in body["words"]] == ["I've", "come", "to", "talk"]


async def test_line_sung_before_curves_were_stored(
    app: FastAPI, db_session: AsyncSession, song_id: uuid.UUID
) -> None:
    async with open_client(app) as client:
        session_id = await start_session(client, song_id)
        await PlaySessionRepository(db_session).add_line_score(
            uuid.UUID(session_id), 0, score=50.0, accuracy=0.5, hit=False
        )
        body = (await client.get(f"/sessions/{session_id}/lines/0/analysis")).json()

    assert (body["status"], body["analysis"]) == ("not_stored", None)


@pytest.mark.parametrize("line", [3, -1])
async def test_unknown_line_is_404(app: FastAPI, song_id: uuid.UUID, line: int) -> None:
    async with open_client(app) as client:
        session_id = await start_session(client, song_id)
        response = await client.get(f"/sessions/{session_id}/lines/{line}/analysis")

    assert response.status_code == 404


async def test_unknown_session_is_404(app: FastAPI) -> None:
    async with open_client(app) as client:
        response = await client.get(f"/sessions/{uuid.uuid4()}/lines/0/analysis")

    assert response.status_code == 404


# --- diagnostics (admin) ---------------------------------------------------------


async def test_diagnostics_show_inputs_parameters_and_word_timing(
    app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await sing(client, song_id, analysis_json, {0: 0.0}, latency_ms=50)
        response = await client.get(
            f"/admin/sessions/{session_id}/lines/0/debug", headers=ADMIN
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "analyzed"
    assert body["analysis"]["result"]["score"] == 100.0
    assert body["latency_ms"] == 50
    assert body["scoring"]["full_credit_semitones"] == 0.5  # hard
    assert body["analysis_version"] == 1
    assert body["pipeline"]["transcriber"] == "whisper-large-v3-turbo"
    reference = body["reference"]
    assert reference["hop_ms"] == 10
    assert len(reference["midi"]) == 70  # 200-900 ms at 10 ms
    assert body["sung_input"] == {
        "hop_ms": HOP_MS,
        "f0_hz": sung_line(analysis_json, 0, delay_frames=5),
    }
    words = body["word_timing"]
    assert [word["text"] for word in words] == ["Hello", "darkness,", "my"]
    assert words[0]["probability"] == 0.93
    assert all(0.0 <= word["voiced_ratio"] <= 1.0 for word in words)
    assert words[1]["voiced_ratio"] == 1.0


async def test_diagnostics_of_an_unsung_line(app: FastAPI, song_id: uuid.UUID) -> None:
    async with open_client(app) as client:
        session_id = await start_session(client, song_id)
        body = (
            await client.get(
                f"/admin/sessions/{session_id}/lines/1/debug", headers=ADMIN
            )
        ).json()

    assert (body["status"], body["sung_input"]) == ("not_sung", None)
    assert len(body["word_timing"]) == 2


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
async def test_diagnostics_require_the_admin_token(
    app: FastAPI, song_id: uuid.UUID, headers: dict[str, str]
) -> None:
    async with open_client(app) as client:
        session_id = await start_session(client, song_id)
        response = await client.get(
            f"/admin/sessions/{session_id}/lines/0/debug", headers=headers
        )

    assert response.status_code == 401


async def test_diagnostics_of_unknown_session_is_404(app: FastAPI) -> None:
    async with open_client(app) as client:
        response = await client.get(
            f"/admin/sessions/{uuid.uuid4()}/lines/0/debug", headers=ADMIN
        )

    assert response.status_code == 404
