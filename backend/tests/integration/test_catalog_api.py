import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.db.session import get_db_session
from app.domain.enums import AssetKind, SongStatus
from app.main import create_app
from app.schemas.analysis import FORMAT_VERSION
from app.storage.dependencies import get_storage
from app.storage.keys import asset_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

INSTRUMENTAL = bytes(range(256)) * 40  # 10 240 fake "MP3" bytes


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
async def client(
    db_session: AsyncSession, storage: LocalStorage
) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(_env_file=None, cors_origins=["http://localhost:5173"]))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def add_song(
    session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    title: str,
    artist: str = "Artist",
    *,
    status: SongStatus = SongStatus.READY,
    analysis: bool = True,
    instrumental: bool = True,
) -> uuid.UUID:
    """Create a song with (optionally) its instrumental and current analysis."""
    songs = SongRepository(session)
    song = await songs.add(title, artist, "es")
    await songs.set_duration(song.id, analysis_json["duration_ms"])
    await songs.set_status(song.id, status)
    if instrumental:
        stored = await storage.save(
            asset_key(song.id, AssetKind.INSTRUMENTAL, "mp3"),
            INSTRUMENTAL,
            "audio/mpeg",
        )
        await SongAssetRepository(session).add(song.id, AssetKind.INSTRUMENTAL, stored)
    if analysis:
        await SongAnalysisRepository(session).add_version(
            song.id, FORMAT_VERSION, analysis_json
        )
    await session.commit()
    return song.id


# --- US-3.1: list and search -------------------------------------------------


async def test_lists_playable_songs_ordered_by_title(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    await add_song(db_session, storage, analysis_json, "Zamba de mi esperanza")
    await add_song(db_session, storage, analysis_json, "chachacha", "Josean Log")

    response = await client.get("/songs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == [
        "chachacha",
        "Zamba de mi esperanza",
    ]
    first = body["items"][0]
    assert first["line_count"] == 3
    assert first["duration_ms"] == 3000
    assert first["reprocessing"] is False
    assert "lines" not in first


async def test_songs_that_are_not_playable_are_hidden(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    await add_song(db_session, storage, analysis_json, "Playable")
    await add_song(
        db_session,
        storage,
        analysis_json,
        "Still processing",
        status=SongStatus.PROCESSING,
        analysis=False,
    )
    await add_song(
        db_session,
        storage,
        analysis_json,
        "Failed",
        status=SongStatus.FAILED,
        analysis=False,
    )
    await add_song(db_session, storage, analysis_json, "No audio", instrumental=False)

    body = (await client.get("/songs")).json()

    assert [item["title"] for item in body["items"]] == ["Playable"]


async def test_song_being_reprocessed_stays_listed(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    await add_song(
        db_session, storage, analysis_json, "Reprocessing", status=SongStatus.PROCESSING
    )

    body = (await client.get("/songs")).json()

    assert body["items"][0]["reprocessing"] is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("cha", ["Chachacha"]),
        ("JOSEAN", ["Chachacha"]),
        ("puerta", ["Desde la primera puerta"]),
        ("brock", ["Desde la primera puerta"]),
        ("zzz", []),
        ("%", []),  # LIKE wildcards are matched literally
        ("_", []),
    ],
)
async def test_search_by_title_or_artist(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    query: str,
    expected: list[str],
) -> None:
    await add_song(db_session, storage, analysis_json, "Chachacha", "Josean Log")
    await add_song(
        db_session,
        storage,
        analysis_json,
        "Desde la primera puerta",
        "Brock Ansiolítiko",
    )

    body = (await client.get("/songs", params={"q": query})).json()

    assert [item["title"] for item in body["items"]] == expected
    assert body["total"] == len(expected)


async def test_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    for title in ["A", "B", "C", "D", "E"]:
        await add_song(db_session, storage, analysis_json, title)

    body = (await client.get("/songs", params={"limit": 2, "offset": 2})).json()

    assert [item["title"] for item in body["items"]] == ["C", "D"]
    assert (body["total"], body["limit"], body["offset"]) == (5, 2, 2)


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 101}]
)
async def test_invalid_list_parameters(
    client: AsyncClient, params: dict[str, str | int]
) -> None:
    assert (await client.get("/songs", params=params)).status_code == 422


# --- US-3.2: detail with lyrics ------------------------------------------------


async def test_detail_has_lyrics_but_not_the_pitch_curve(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")
    current = await SongAnalysisRepository(db_session).get_current(song_id)
    assert current is not None

    response = await client.get(f"/songs/{song_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(song_id)
    assert body["analysis_id"] == str(current.id)
    assert body["analysis_version"] == 1
    assert body["lines"] == analysis_json["lines"]
    assert "pitch" not in body


@pytest.mark.parametrize("playable", [False, True])
async def test_detail_of_unavailable_song_is_404(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    playable: bool,
) -> None:
    song_id = (
        uuid.uuid4()
        if playable
        else await add_song(
            db_session, storage, analysis_json, "Pending", analysis=False
        )
    )

    assert (await client.get(f"/songs/{song_id}")).status_code == 404


# --- cross-cutting -------------------------------------------------------------


async def test_large_json_responses_are_gzipped(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}", headers={"Accept-Encoding": "gzip"}
    )

    assert response.headers["content-encoding"] == "gzip"
    assert response.json()["lines"]  # httpx decompresses transparently


async def test_cors_allows_the_web_client_origin(client: AsyncClient) -> None:
    response = await client.get("/songs", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_rejects_other_origins(client: AsyncClient) -> None:
    response = await client.get("/songs", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers


# --- US-3.3: instrumental streaming --------------------------------------------


async def test_instrumental_without_range_is_served_whole(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}/instrumental", headers={"Accept-Encoding": "gzip"}
    )

    assert response.status_code == 200
    assert response.content == INSTRUMENTAL
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(INSTRUMENTAL))
    assert "content-encoding" not in response.headers  # audio is never gzipped


@pytest.mark.parametrize(
    ("range_header", "start", "stop"),
    [
        ("bytes=0-99", 0, 100),
        ("bytes=5000-", 5000, len(INSTRUMENTAL)),
        ("bytes=-256", len(INSTRUMENTAL) - 256, len(INSTRUMENTAL)),
        ("bytes=10000-99999", 10000, len(INSTRUMENTAL)),
    ],
)
async def test_instrumental_range_requests(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    range_header: str,
    start: int,
    stop: int,
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}/instrumental", headers={"Range": range_header}
    )

    assert response.status_code == 206
    assert response.content == INSTRUMENTAL[start:stop]
    assert response.headers["content-range"] == (
        f"bytes {start}-{stop - 1}/{len(INSTRUMENTAL)}"
    )
    assert response.headers["content-length"] == str(stop - start)


async def test_unsatisfiable_range_is_416(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}/instrumental", headers={"Range": "bytes=999999-"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(INSTRUMENTAL)}"


async def test_malformed_range_serves_the_whole_file(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}/instrumental", headers={"Range": "bytes=0-10,20-30"}
    )

    assert response.status_code == 200
    assert response.content == INSTRUMENTAL


async def test_instrumental_of_unavailable_song_is_404(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    pending = await add_song(
        db_session, storage, analysis_json, "Pending", analysis=False
    )

    assert (await client.get(f"/songs/{pending}/instrumental")).status_code == 404
    assert (await client.get(f"/songs/{uuid.uuid4()}/instrumental")).status_code == 404


async def test_cors_exposes_range_headers(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(
        f"/songs/{song_id}/instrumental",
        headers={"Origin": "http://localhost:5173", "Range": "bytes=0-9"},
    )

    exposed = response.headers["access-control-expose-headers"].lower()
    assert "content-range" in exposed
    assert "accept-ranges" in exposed


# --- US-3.4: reference pitch -----------------------------------------------------


async def test_pitch_of_the_whole_song(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    response = await client.get(f"/songs/{song_id}/pitch")

    assert response.status_code == 200
    body = response.json()
    assert body["line_index"] is None
    assert (body["start_ms"], body["hop_ms"]) == (0, 10)
    assert body["midi"] == analysis_json["pitch"]["midi"]
    assert body["confidence"] == analysis_json["pitch"]["confidence"]


async def test_pitch_of_one_line(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")

    body = (await client.get(f"/songs/{song_id}/pitch", params={"line": 1})).json()

    # Line 1 spans 1000-1800 ms: frames 100..179.
    assert (body["line_index"], body["start_ms"]) == (1, 1000)
    assert body["midi"] == analysis_json["pitch"]["midi"][100:180]
    assert body["confidence"] == analysis_json["pitch"]["confidence"][100:180]


async def test_pitch_errors(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
) -> None:
    song_id = await add_song(db_session, storage, analysis_json, "Song")
    pending = await add_song(
        db_session, storage, analysis_json, "Pending", analysis=False
    )

    assert (await client.get(f"/songs/{song_id}/pitch?line=3")).status_code == 404
    assert (await client.get(f"/songs/{song_id}/pitch?line=-1")).status_code == 422
    assert (await client.get(f"/songs/{pending}/pitch")).status_code == 404
    assert (await client.get(f"/songs/{uuid.uuid4()}/pitch")).status_code == 404
