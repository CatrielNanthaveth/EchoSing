import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import summarize
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.tools import ToolError
from app.schemas.analysis import LevelCurve
from app.services.pipeline.errors import StageError
from app.services.pipeline.level import LevelStage, load_level
from app.storage.keys import asset_key, work_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

CURVE = LevelCurve(hop_ms=10, db=[-90.0, -30.0, -12.5, -40.0])


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _song_with_vocals(session: AsyncSession, storage: LocalStorage) -> uuid.UUID:
    song = await SongRepository(session).add("Song", "Artist")
    stored = await storage.save(
        asset_key(song.id, AssetKind.VOCALS, "flac"), b"vocals-audio", "audio/flac"
    )
    await SongAssetRepository(session).add(song.id, AssetKind.VOCALS, stored)
    await session.commit()
    return song.id


async def test_measures_the_vocals_and_saves_the_curve(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    measured: list[bytes] = []

    async def extractor(audio: Path) -> LevelCurve:
        measured.append(audio.read_bytes())
        return CURVE

    result = await LevelStage(db_session, storage, extractor).run(song_id)

    assert measured == [b"vocals-audio"]
    assert result.frame_count == 4
    assert result.artifact_key == work_key(song_id, "level.json")
    assert await load_level(storage, song_id) == CURVE
    assert summarize(result)


async def test_decoding_failure_saves_nothing(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)

    async def failing(audio: Path) -> LevelCurve:
        raise ToolError("ffmpeg failed")

    with pytest.raises(ToolError):
        await LevelStage(db_session, storage, failing).run(song_id)

    assert not await storage.exists(work_key(song_id, "level.json"))


async def test_missing_song_or_vocals_raises(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = LevelStage(db_session, storage)
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song = await SongRepository(db_session).add("Not separated", "Artist")
    with pytest.raises(StageError, match="run the 'separate' stage first"):
        await stage.run(song.id)
