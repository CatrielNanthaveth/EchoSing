"""Rap mode end to end: sessions, live scoring, results, practice and attempts."""

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.songs import SongAnalysisRepository
from app.db.session import get_db_session
from app.main import create_app
from app.storage.dependencies import get_storage
from app.storage.local import LocalStorage
from tests.integration.catalog_helpers import add_song
from tests.integration.test_session_socket import connect, open_client, receive

pytestmark = pytest.mark.integration

TOKEN = "admin-secret"
HOP_MS = 10
TAIL_MS = 300
# Syllable attacks of the three fixture lines (200-900, 1000-1800, 2000-2900 ms).
ATTACKS_MS = [[250, 450, 650], [1050, 1300, 1550], [2050, 2300, 2550, 2750]]


def level_db(attacks_ms: Sequence[float], length_ms: float, peak: float) -> list[float]:
    """A vocal level with a sharp attack at each time, decaying after it."""
    db = np.full(int(length_ms // HOP_MS), -60.0)
    for time in attacks_ms:
        start = int(round(time / HOP_MS))
        decay = peak - 2.0 * np.arange(12)
        end = min(start + decay.size, db.size)
        if 0 <= start < db.size:
            db[start:end] = np.maximum(db[start:end], decay[: end - start])
    return [round(float(value), 1) for value in db]


def with_level(analysis_json: dict[str, Any]) -> dict[str, Any]:
    attacks = [time for line in ATTACKS_MS for time in line]
    level = {"hop_ms": HOP_MS, "db": level_db(attacks, 3000, -15)}
    return {**analysis_json, "level": level}


def rap_line(
    analysis: dict[str, Any], index: int, offset_ms: float = 0
) -> dict[str, Any]:
    """What a client sends for a rapped line: level (and some pitch) per frame."""
    line = analysis["lines"][index]
    length = line["end_ms"] - line["start_ms"] + TAIL_MS
    attacks = [t - line["start_ms"] + offset_ms for t in ATTACKS_MS[index]]
    levels = level_db(attacks, length, -25)
    return {
        "type": "line_pitch",
        "line_index": index,
        "hop_ms": HOP_MS,
        "f0_hz": [0.0 if db < -40 else 150.0 for db in levels],  # pitch is ignored
        "level_db": levels,
    }


@pytest.fixture
def app(db_session: AsyncSession, storage: LocalStorage) -> FastAPI:
    application = create_app(Settings(_env_file=None, admin_token=TOKEN))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = session_override
    application.dependency_overrides[get_storage] = lambda: storage
    return application


@pytest.fixture
def rap_analysis(analysis_json: dict[str, Any]) -> dict[str, Any]:
    return with_level(analysis_json)


@pytest.fixture
async def song_id(
    db_session: AsyncSession, storage: LocalStorage, rap_analysis: dict[str, Any]
) -> uuid.UUID:
    return await add_song(db_session, storage, rap_analysis, "Rap")


async def start(client: AsyncClient, song: uuid.UUID, mode: str = "rhythm") -> str:
    response = await client.post(
        "/sessions",
        json={"song_id": str(song), "player_name": "MC", "mode": mode},
    )
    assert response.status_code == 201, response.text
    session_id: str = response.json()["session_id"]
    return session_id


async def test_song_detail_tells_if_rap_mode_is_available(
    app: FastAPI,
    db_session: AsyncSession,
    storage: LocalStorage,
    song_id: uuid.UUID,
    analysis_json: dict[str, Any],
) -> None:
    plain = await add_song(db_session, storage, analysis_json, "Plain")
    async with open_client(app) as client:
        rap = (await client.get(f"/songs/{song_id}")).json()
        other = (await client.get(f"/songs/{plain}")).json()

    assert (rap["rap_mode_available"], other["rap_mode_available"]) == (True, False)


async def test_rap_session_scores_the_timing_of_the_syllables(
    app: FastAPI, song_id: uuid.UUID, rap_analysis: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await start(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(json.dumps(rap_line(rap_analysis, 0)))
            on_time = await receive(ws)
            await ws.send_text(json.dumps(rap_line(rap_analysis, 1, offset_ms=70)))
            late = await receive(ws)
            await ws.send_text(json.dumps({"type": "finish"}))
            summary = await receive(ws)
        results = (await client.get(f"/sessions/{session_id}/results")).json()

    assert on_time["score"] == 100.0
    assert late["score"] == pytest.approx(50.0, abs=0.01)  # (100-70)/(100-40)
    assert results["mode"] == "rhythm"
    unsung = results["lines"][2]
    assert (unsung["sung"], unsung["score"]) == (False, 0.0)
    # Weighted by attacks: (3 * 100 + 3 * 50 + 4 * 0) / 10.
    assert summary["total_score"] == pytest.approx(45.0, abs=0.01)


async def test_rap_lines_need_the_microphone_level(
    app: FastAPI, song_id: uuid.UUID, rap_analysis: dict[str, Any]
) -> None:
    message = rap_line(rap_analysis, 0)
    del message["level_db"]
    async with open_client(app) as client:
        session_id = await start(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(json.dumps(message))
            error = await receive(ws)

    assert error["code"] == "invalid_message"
    assert "level_db" in error["detail"]


async def test_rap_mode_needs_the_vocals_level(
    app: FastAPI,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    plain = await add_song(db_session, storage, analysis_json, "Plain")
    async with open_client(app) as client:
        response = await client.post(
            "/sessions",
            json={"song_id": str(plain), "player_name": "MC", "mode": "rhythm"},
        )

    assert response.status_code == 409
    assert "level" in response.json()["detail"]


async def test_practice_and_diagnostics_explain_rap_lines(
    app: FastAPI, song_id: uuid.UUID, rap_analysis: dict[str, Any]
) -> None:
    async with open_client(app) as client:
        session_id = await start(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(json.dumps(rap_line(rap_analysis, 2, offset_ms=-30)))
            await receive(ws)
        practice = (await client.get(f"/sessions/{session_id}/lines/2/analysis")).json()
        debug = (
            await client.get(
                f"/admin/sessions/{session_id}/lines/2/debug",
                headers={"X-Admin-Token": TOKEN},
            )
        ).json()

    assert (practice["mode"], practice["status"], practice["analysis"]) == (
        "rhythm",
        "analyzed",
        None,
    )
    rhythm = practice["rhythm"]
    assert rhythm["reference_onsets_ms"] == [50.0, 300.0, 550.0, 750.0]
    assert rhythm["timing_offset_ms"] == -30.0
    assert rhythm["result"]["score"] == 100.0
    assert debug["rhythm_scoring"]["full_credit_ms"] == 40.0
    assert len(debug["reference_level"]["db"]) == 90  # 2000-2900 ms


@pytest.mark.parametrize(
    ("offset_ms", "difficulty", "expected"),
    [(0, "normal", 100.0), (60, "easy", 87.5), (60, "hard", 33.33)],
)
async def test_rap_attempts(
    app: FastAPI,
    db_session: AsyncSession,
    song_id: uuid.UUID,
    rap_analysis: dict[str, Any],
    offset_ms: float,
    difficulty: str,
    expected: float,
) -> None:
    identity = await SongAnalysisRepository(db_session).get_current_identity(song_id)
    assert identity is not None
    sung = rap_line(rap_analysis, 0, offset_ms=offset_ms)
    async with open_client(app) as client:
        response = await client.post(
            f"/songs/{song_id}/lines/0/attempt",
            json={
                "analysis_id": str(identity[0]),
                "hop_ms": HOP_MS,
                "f0_hz": sung["f0_hz"],
                "level_db": sung["level_db"],
                "mode": "rhythm",
                "difficulty": difficulty,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["mode"], body["analysis"]) == ("rhythm", None)
    assert body["rhythm"]["result"]["score"] == pytest.approx(expected, abs=0.01)


async def test_rap_attempts_need_level_and_a_level_curve(
    app: FastAPI,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    plain = await add_song(db_session, storage, analysis_json, "Plain")
    identity = await SongAnalysisRepository(db_session).get_current_identity(plain)
    assert identity is not None
    body = {
        "analysis_id": str(identity[0]),
        "hop_ms": HOP_MS,
        "f0_hz": [0.0, 150.0],
        "mode": "rhythm",
    }
    async with open_client(app) as client:
        without_level = await client.post(f"/songs/{plain}/lines/0/attempt", json=body)
        without_curve = await client.post(
            f"/songs/{plain}/lines/0/attempt",
            json={**body, "level_db": [-60.0, -20.0]},
        )

    assert without_level.status_code == 422
    assert without_curve.status_code == 409
