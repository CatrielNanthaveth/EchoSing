import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlaySession
from app.db.repositories.songs import SongAnalysisRepository
from app.domain.enums import Difficulty, PlaySessionStatus
from app.storage.local import LocalStorage
from tests.integration.catalog_helpers import add_song

pytestmark = pytest.mark.integration


# --- US-5.1: create a session --------------------------------------------------------


async def test_create_session_binds_the_current_analysis(
    api_client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")
    current = await SongAnalysisRepository(db_session).get_current(song_id)
    assert current is not None

    response = await api_client.post(
        "/sessions",
        json={
            "song_id": str(song_id),
            "player_name": "  Ana ",
            "latency_offset_ms": 120,
            "difficulty": "easy",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["song_id"] == str(song_id)
    assert body["analysis_id"] == str(current.id)
    assert body["analysis_version"] == 1
    assert body["line_count"] == 3
    assert (body["player_name"], body["latency_offset_ms"]) == ("Ana", 120)
    assert body["difficulty"] == "easy"
    stored = await db_session.get(PlaySession, uuid.UUID(body["session_id"]))
    assert stored is not None
    assert stored.status is PlaySessionStatus.ACTIVE
    assert stored.analysis_id == current.id
    assert stored.difficulty is Difficulty.EASY


async def test_latency_defaults_to_zero_and_difficulty_to_normal(
    api_client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await api_client.post(
        "/sessions", json={"song_id": str(song_id), "player_name": "Ana"}
    )

    assert response.json()["latency_offset_ms"] == 0
    assert response.json()["difficulty"] == "normal"


async def test_session_for_unavailable_song_is_404(
    api_client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    pending = await add_song(
        db_session, storage, analysis_json, "Pending", analysis=False
    )

    for song_id in (pending, uuid.uuid4()):
        response = await api_client.post(
            "/sessions", json={"song_id": str(song_id), "player_name": "Ana"}
        )
        assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"player_name": "Ana"},
        {"song_id": "not-a-uuid", "player_name": "Ana"},
        {"song_id": str(uuid.uuid4()), "player_name": "   "},
        {"song_id": str(uuid.uuid4()), "player_name": "x" * 51},
        {"song_id": str(uuid.uuid4()), "player_name": "Ana", "latency_offset_ms": 5000},
        {"song_id": str(uuid.uuid4()), "player_name": "Ana", "latency_offset_ms": -501},
        {"song_id": str(uuid.uuid4()), "player_name": "Ana", "difficulty": "extreme"},
    ],
)
async def test_invalid_session_requests(
    api_client: AsyncClient, body: dict[str, object]
) -> None:
    assert (await api_client.post("/sessions", json=body)).status_code == 422
