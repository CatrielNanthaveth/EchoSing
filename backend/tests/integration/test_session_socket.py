import copy
import json
import math
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import LineScore, PlaySession
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.session import get_db_session
from app.domain.enums import PlaySessionStatus
from app.main import create_app
from app.schemas.sessions import LinePitchMessage, SessionCreate
from app.services.play_sessions import LineAlreadyScoredError, PlaySessionService
from app.storage.dependencies import get_storage
from app.storage.local import LocalStorage
from tests.integration.catalog_helpers import add_song

pytestmark = pytest.mark.integration

HOP_MS = 10


@pytest.fixture
def ws_app(db_session: AsyncSession, storage: LocalStorage) -> FastAPI:
    app = create_app(Settings(_env_file=None))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_storage] = lambda: storage
    return app


@asynccontextmanager
async def open_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP + WebSocket client for the app.

    Opened inside each test (not in a fixture): the transport's anyio task
    group must be entered and exited in the same task.
    """
    async with AsyncClient(
        transport=ASGIWebSocketTransport(app=app), base_url="http://test"
    ) as client:
        yield client


def connect(
    client: AsyncClient, session_id: str, *, max_message_size_bytes: int = 65_536
) -> AbstractAsyncContextManager[AsyncWebSocketSession]:
    return aconnect_ws(
        f"http://test/ws/sessions/{session_id}",
        client,
        max_message_size_bytes=max_message_size_bytes,
    )


def sung_line(
    analysis: dict[str, Any],
    line_index: int,
    *,
    semitones: float = 0.0,
    delay_frames: int = 0,
    tail_frames: int = 30,
) -> list[float]:
    """The reference pitch of a line in Hz, as a perfect singer would send it."""
    line = analysis["lines"][line_index]
    pitch = analysis["pitch"]
    first = math.ceil(line["start_ms"] / HOP_MS)
    last = min(math.ceil(line["end_ms"] / HOP_MS) + tail_frames, len(pitch["midi"]))
    hz = [
        440.0 * 2 ** ((midi + semitones - 69) / 12)
        if midi is not None and confidence >= 50
        else 0.0
        for midi, confidence in zip(
            pitch["midi"][first:last], pitch["confidence"][first:last], strict=True
        )
    ]
    return [0.0] * delay_frames + hz


def pitch_message(line_index: int, f0_hz: list[float]) -> str:
    return json.dumps(
        {
            "type": "line_pitch",
            "line_index": line_index,
            "hop_ms": HOP_MS,
            "f0_hz": f0_hz,
        }
    )


async def start_session(
    client: AsyncClient, song_id: uuid.UUID, latency_ms: int = 0
) -> str:
    response = await client.post(
        "/sessions",
        json={
            "song_id": str(song_id),
            "player_name": "Ana",
            "latency_offset_ms": latency_ms,
        },
    )
    session_id: str = response.json()["session_id"]
    return session_id


async def receive(ws: AsyncWebSocketSession) -> dict[str, Any]:
    message: dict[str, Any] = json.loads(await ws.receive_text())
    return message


@pytest.fixture
async def song_id(
    db_session: AsyncSession, storage: LocalStorage, analysis_json: dict[str, Any]
) -> uuid.UUID:
    return await add_song(db_session, storage, analysis_json, "Song")


# --- US-5.2: real-time scoring --------------------------------------------------------


async def test_perfect_lines_score_100_and_build_a_streak(
    ws_app: FastAPI,
    db_session: AsyncSession,
    song_id: uuid.UUID,
    analysis_json: dict[str, Any],
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            ready = await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            first = await receive(ws)
            await ws.send_text(pitch_message(1, sung_line(analysis_json, 1)))
            second = await receive(ws)

    assert ready["type"] == "ready"
    assert (ready["line_count"], ready["scored_lines"]) == (3, [])
    assert first == {
        "type": "line_score",
        "line_index": 0,
        "scorable": True,
        "score": 100.0,
        "accuracy": 1.0,
        "hit": True,
        "streak": 1,
    }
    assert (second["score"], second["streak"]) == (100.0, 2)
    rows = (
        await db_session.scalars(
            select(LineScore).where(LineScore.session_id == uuid.UUID(session_id))
        )
    ).all()
    assert [(r.line_index, r.score, r.scorable) for r in rows] == [
        (0, 100.0, True),
        (1, 100.0, True),
    ]
    assert all(r.voiced_frames > 0 for r in rows)


async def test_detuned_line_scores_lower_and_breaks_the_streak(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            await receive(ws)
            await ws.send_text(
                pitch_message(1, sung_line(analysis_json, 1, semitones=2.5))
            )
            detuned = await receive(ws)

    assert detuned["score"] < 20
    assert (detuned["hit"], detuned["streak"]) == (False, 0)


async def test_session_latency_is_compensated(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id, latency_ms=150)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(
                pitch_message(0, sung_line(analysis_json, 0, delay_frames=15))
            )
            result = await receive(ws)

    assert result["score"] == 100.0


async def test_line_with_too_little_singing_is_recorded_unscored(
    ws_app: FastAPI,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    spoken = copy.deepcopy(analysis_json)
    spoken["pitch"]["confidence"] = [0] * len(spoken["pitch"]["confidence"])
    song = await add_song(db_session, storage, spoken, "Spoken")

    async with open_client(ws_app) as client:
        session_id = await start_session(client, song)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, [220.0] * 80))
            result = await receive(ws)

    assert (result["scorable"], result["score"], result["accuracy"]) == (
        False,
        None,
        None,
    )
    row = await db_session.scalar(
        select(LineScore).where(LineScore.session_id == uuid.UUID(session_id))
    )
    assert row is not None
    assert (row.scorable, row.score) == (False, None)


# --- errors keep the connection open --------------------------------------------------


async def test_errors_are_reported_without_closing(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            await receive(ws)

            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            duplicate = await receive(ws)
            await ws.send_text(pitch_message(7, [220.0]))
            unknown = await receive(ws)
            await ws.send_text("not json")
            garbage = await receive(ws)
            await ws.send_text(pitch_message(1, [-5.0]))
            negative = await receive(ws)
            await ws.send_text(json.dumps({"type": "line_pitch", "line_index": 1}))
            incomplete = await receive(ws)

            # The connection is still usable after all those errors.
            await ws.send_text(pitch_message(1, sung_line(analysis_json, 1)))
            still_working = await receive(ws)

    assert duplicate["code"] == "line_already_scored"
    assert unknown["code"] == "unknown_line"
    assert {garbage["code"], negative["code"], incomplete["code"]} == {
        "invalid_message"
    }
    assert still_working["score"] == 100.0


async def test_too_many_frames_are_rejected(
    ws_app: FastAPI, song_id: uuid.UUID
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id, max_message_size_bytes=10**6) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, [220.0] * 6001))
            result = await receive(ws)

    assert result["code"] == "invalid_message"


# --- connection lifecycle -------------------------------------------------------------


async def test_reconnecting_resumes_the_session(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            await receive(ws)

        async with connect(client, session_id) as ws:
            ready = await receive(ws)
            await ws.send_text(pitch_message(1, sung_line(analysis_json, 1)))
            resumed = await receive(ws)

    assert ready["scored_lines"] == [0]
    assert resumed["streak"] == 2  # the streak continues across connections


async def test_unknown_session_is_closed(ws_app: FastAPI) -> None:
    async with open_client(ws_app) as client, connect(client, str(uuid.uuid4())) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            await ws.receive_text()

    assert closed.value.code == 4404


async def test_finished_session_is_closed(
    ws_app: FastAPI, db_session: AsyncSession, song_id: uuid.UUID
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        play_session = await db_session.get(PlaySession, uuid.UUID(session_id))
        assert play_session is not None
        play_session.status = PlaySessionStatus.FINISHED
        await db_session.commit()

        async with connect(client, session_id) as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                await ws.receive_text()

    assert closed.value.code == 4409


async def test_line_scored_concurrently_by_another_connection(
    db_session: AsyncSession, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    service = PlaySessionService(db_session)
    created = await service.create(
        SessionCreate(song_id=song_id, player_name="Ana", latency_offset_ms=0)
    )
    live = await service.open(created.session_id)
    # Another socket scores line 0 after this one loaded the session.
    await PlaySessionRepository(db_session).add_line_score(
        created.session_id, 0, 50.0, 0.5, False, voiced_frames=10
    )
    await db_session.commit()

    message = LinePitchMessage(
        type="line_pitch",
        line_index=0,
        hop_ms=HOP_MS,
        f0_hz=sung_line(analysis_json, 0),
    )
    with pytest.raises(LineAlreadyScoredError):
        await service.score_line(live, message)

    assert 0 not in live.results


# --- US-5.3 / US-5.4: finish and results ----------------------------------------


FINISH = json.dumps({"type": "finish"})


async def test_finish_counts_unsung_lines_as_zero_and_closes(
    ws_app: FastAPI,
    db_session: AsyncSession,
    song_id: uuid.UUID,
    analysis_json: dict[str, Any],
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            for index in (0, 1):  # line 2 is never sung
                await ws.send_text(
                    pitch_message(index, sung_line(analysis_json, index))
                )
                await receive(ws)
            await ws.send_text(FINISH)
            summary = await receive(ws)
            with pytest.raises(WebSocketDisconnect) as closed:
                await ws.receive_text()

    assert closed.value.code == 1000
    assert summary["type"] == "session_summary"
    assert 0 < summary["total_score"] < 100  # line 2 counts as 0
    assert (summary["best_streak"], summary["scored_lines"], summary["hit_lines"]) == (
        2,
        3,
        2,
    )
    play_session = await db_session.get(PlaySession, uuid.UUID(session_id))
    assert play_session is not None
    assert play_session.status is PlaySessionStatus.FINISHED
    assert play_session.finished_at is not None
    assert play_session.total_score == summary["total_score"]
    assert play_session.best_streak == 2
    stored = (
        await db_session.scalars(
            select(LineScore.line_index).where(
                LineScore.session_id == uuid.UUID(session_id)
            )
        )
    ).all()
    assert sorted(stored) == [0, 1]  # unsung lines are not stored


async def test_finish_without_singing_scores_zero(
    ws_app: FastAPI, song_id: uuid.UUID
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(FINISH)
            summary = await receive(ws)

    assert (summary["total_score"], summary["hit_lines"]) == (0.0, 0)


async def test_results_of_an_active_session(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            await receive(ws)
        response = await client.get(f"/sessions/{session_id}/results")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["finished_at"] is None
    assert body["player_name"] == "Ana"
    # Totals so far only cover the line already sung.
    assert (body["totals"]["total_score"], body["totals"]["scored_lines"]) == (
        100.0,
        1,
    )
    first, second = body["lines"][0], body["lines"][1]
    assert first["text"] == analysis_json["lines"][0]["text"]
    assert (first["sung"], first["score"], first["hit"]) == (True, 100.0, True)
    assert (second["sung"], second["score"], second["scorable"]) == (
        False,
        None,
        None,
    )


async def test_results_of_a_finished_session_match_the_summary(
    ws_app: FastAPI, song_id: uuid.UUID, analysis_json: dict[str, Any]
) -> None:
    async with open_client(ws_app) as client:
        session_id = await start_session(client, song_id)
        async with connect(client, session_id) as ws:
            await receive(ws)
            await ws.send_text(pitch_message(0, sung_line(analysis_json, 0)))
            await receive(ws)
            await ws.send_text(FINISH)
            summary = await receive(ws)
        body = (await client.get(f"/sessions/{session_id}/results")).json()

    assert body["status"] == "finished"
    assert body["finished_at"] is not None
    assert body["totals"] == {k: v for k, v in summary.items() if k != "type"}
    unsung = body["lines"][2]
    assert (unsung["sung"], unsung["scorable"], unsung["score"]) == (False, True, 0.0)


async def test_results_of_unknown_session_is_404(ws_app: FastAPI) -> None:
    async with open_client(ws_app) as client:
        response = await client.get(f"/sessions/{uuid.uuid4()}/results")

    assert response.status_code == 404
