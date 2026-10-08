import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Song
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.domain.enums import SongStatus
from app.schemas.analysis import FORMAT_VERSION, SongAnalysisData, parse_analysis
from app.services.pipeline.errors import StageError
from app.services.pipeline.manifest import update_manifest
from app.services.pipeline.persist import PersistStage
from app.services.pipeline.segmentation import SegmentedLyrics
from app.storage.keys import work_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

MODELS = {
    "separator": "htdemucs(shifts=5)",
    "transcriber": "whisper-large-v3-turbo",
    "pitch_extractor": "torchcrepe-full-viterbi",
}


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _song(session: AsyncSession, duration_ms: int | None = 3000) -> uuid.UUID:
    song = await SongRepository(session).add("Song", "Artist", "es")
    if duration_ms is not None:
        await SongRepository(session).set_duration(song.id, duration_ms)
    await session.commit()
    return song.id


async def _artifacts(
    storage: LocalStorage,
    song_id: uuid.UUID,
    analysis_json: dict[str, Any],
    *,
    lines: bool = True,
    pitch: bool = True,
    models: dict[str, str] | None = None,
) -> None:
    fixture = SongAnalysisData.model_validate(analysis_json)
    if lines:
        lyrics = SegmentedLyrics(source="official", lines=fixture.lines)
        await storage.save(
            work_key(song_id, "lines.json"),
            lyrics.model_dump_json().encode(),
            "application/json",
        )
    if pitch:
        await storage.save(
            work_key(song_id, "pitch.json"),
            fixture.pitch.model_dump_json().encode(),
            "application/json",
        )
    await update_manifest(storage, song_id, **(MODELS if models is None else models))


async def test_publishes_the_analysis_and_marks_the_song_ready(
    db_session: AsyncSession, storage: LocalStorage, analysis_json: dict[str, Any]
) -> None:
    song_id = await _song(db_session)
    await _artifacts(storage, song_id, analysis_json)

    result = await PersistStage(db_session, storage).run(song_id)

    assert (result.version, result.lines, result.frames) == (1, 3, 300)
    assert result.pipeline.separator == "htdemucs(shifts=5)"
    assert result.pipeline.language == "es"
    current = await SongAnalysisRepository(db_session).get_current(song_id)
    assert current is not None
    assert current.id == result.analysis_id
    stored = parse_analysis(current.format_version, current.data)
    assert stored.format_version == FORMAT_VERSION
    assert stored.pipeline.transcriber == "whisper-large-v3-turbo"
    assert [line.text for line in stored.lines] == [
        line["text"] for line in analysis_json["lines"]
    ]
    song = await db_session.get(Song, song_id)
    assert song is not None
    assert song.status is SongStatus.READY


async def test_reprocessing_creates_a_new_current_version(
    db_session: AsyncSession, storage: LocalStorage, analysis_json: dict[str, Any]
) -> None:
    song_id = await _song(db_session)
    await _artifacts(storage, song_id, analysis_json)
    stage = PersistStage(db_session, storage)

    first = await stage.run(song_id)
    second = await stage.run(song_id)

    assert (first.version, second.version) == (1, 2)
    current = await SongAnalysisRepository(db_session).get_current(song_id)
    assert current is not None
    assert current.id == second.analysis_id


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({"lines": False}, "run 'segment' first"),
        ({"pitch": False}, "run 'pitch' first"),
        ({"models": {"separator": "htdemucs"}}, "transcriber, pitch_extractor"),
    ],
)
async def test_missing_inputs_publish_nothing(
    db_session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    setup: dict[str, Any],
    message: str,
) -> None:
    song_id = await _song(db_session)
    await _artifacts(storage, song_id, analysis_json, **setup)

    with pytest.raises(StageError, match=message):
        await PersistStage(db_session, storage).run(song_id)

    assert await SongAnalysisRepository(db_session).get_current(song_id) is None


async def test_song_without_duration_or_missing_song(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = PersistStage(db_session, storage)
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song_id = await _song(db_session, duration_ms=None)
    with pytest.raises(StageError, match="run 'separate' first"):
        await stage.run(song_id)


async def test_invalid_analysis_is_rejected(
    db_session: AsyncSession, storage: LocalStorage, analysis_json: dict[str, Any]
) -> None:
    # The lines end at 2.9 s but the song is said to last only 2 s.
    song_id = await _song(db_session, duration_ms=2000)
    await _artifacts(storage, song_id, analysis_json)

    with pytest.raises(StageError, match="is invalid"):
        await PersistStage(db_session, storage).run(song_id)

    assert await SongAnalysisRepository(db_session).get_current(song_id) is None
    song = await db_session.get(Song, song_id)
    assert song is not None
    assert song.status is SongStatus.PENDING
