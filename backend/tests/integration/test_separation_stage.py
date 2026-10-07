import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Song, SongAsset
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind, SeparationPreset
from app.ml.audio import InvalidAudioError
from app.ml.separation import (
    DemucsSeparator,
    RoformerSeparator,
    SeparatedStems,
    SeparationError,
)
from app.services.pipeline.errors import StageError
from app.services.pipeline.separation import (
    DurationProbe,
    SeparationStage,
    build_separation_stage,
)
from app.storage.keys import asset_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

DURATION_MS = 183_250


class FakeSeparator:
    """Writes small fake stems instead of running Demucs."""

    def __init__(self, *, fail: bool = False, vocals: bytes = b"vocals") -> None:
        self.fail = fail
        self.vocals = vocals
        self.calls: list[Path] = []

    @property
    def name(self) -> str:
        return "fake-demucs"

    async def separate(self, audio: Path, output_dir: Path) -> SeparatedStems:
        self.calls.append(audio)
        if self.fail:
            raise SeparationError("CUDA out of memory")
        output_dir.mkdir(parents=True)
        (output_dir / "vocals.flac").write_bytes(self.vocals)
        (output_dir / "no_vocals.flac").write_bytes(b"accompaniment")
        return SeparatedStems(
            vocals=output_dir / "vocals.flac",
            accompaniment=output_dir / "no_vocals.flac",
        )


async def fake_probe(path: Path) -> int:
    return DURATION_MS


async def invalid_probe(path: Path) -> int:
    raise InvalidAudioError(f"Not a readable audio file: {path.name}")


async def fake_encode_mp3(source: Path, destination: Path) -> None:
    destination.write_bytes(b"mp3:" + source.read_bytes())


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _song_with_original(session: AsyncSession, storage: LocalStorage) -> Song:
    song = await SongRepository(session).add("Song", "Artist")
    stored = await storage.save(
        asset_key(song.id, AssetKind.ORIGINAL, "mp3"), b"original-audio", "audio/mpeg"
    )
    await SongAssetRepository(session).add(song.id, AssetKind.ORIGINAL, stored)
    # As in production: the upload (US-2.1) is committed before stages run.
    await session.commit()
    return song


class FakeFactory:
    """Separator factory that records the presets it was asked for."""

    def __init__(self, separator: FakeSeparator) -> None:
        self.separator = separator
        self.presets: list[SeparationPreset] = []

    def __call__(self, preset: SeparationPreset) -> FakeSeparator:
        self.presets.append(preset)
        return self.separator


def _stage(
    session: AsyncSession,
    storage: LocalStorage,
    separator: FakeSeparator | FakeFactory,
    *,
    probe: DurationProbe = fake_probe,
) -> SeparationStage:
    factory = (
        separator if isinstance(separator, FakeFactory) else FakeFactory(separator)
    )
    return SeparationStage(
        session, storage, factory, probe=probe, encode_mp3=fake_encode_mp3
    )


async def _read(storage: LocalStorage, key: str) -> bytes:
    return b"".join([chunk async for chunk in await storage.stream(key)])


async def _assets(
    session: AsyncSession, song_id: uuid.UUID
) -> dict[AssetKind, SongAsset]:
    rows = await session.scalars(select(SongAsset).where(SongAsset.song_id == song_id))
    return {row.kind: row for row in rows}


async def test_stores_stems_and_duration(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    separator = FakeSeparator()

    result = await _stage(db_session, storage, separator).run(song.id)

    assert result.duration_ms == DURATION_MS
    assert result.preset is SeparationPreset.DEMUCS
    assert result.separator == "fake-demucs"
    assert separator.calls[0].read_bytes() == b"original-audio"

    assets = await _assets(db_session, song.id)
    assert set(assets) == {AssetKind.ORIGINAL, AssetKind.VOCALS, AssetKind.INSTRUMENTAL}
    vocals, instrumental = assets[AssetKind.VOCALS], assets[AssetKind.INSTRUMENTAL]
    assert vocals.storage_key == f"songs/{song.id}/vocals.flac"
    assert vocals.content_type == "audio/flac"
    assert instrumental.storage_key == f"songs/{song.id}/instrumental.mp3"
    assert instrumental.content_type == "audio/mpeg"
    assert await _read(storage, vocals.storage_key) == b"vocals"
    assert await _read(storage, instrumental.storage_key) == b"mp3:accompaniment"
    assert instrumental.size_bytes == len(b"mp3:accompaniment")

    refreshed = await db_session.get(Song, song.id)
    assert refreshed is not None
    assert refreshed.duration_ms == DURATION_MS


async def test_reprocessing_replaces_stems(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    await _stage(db_session, storage, FakeSeparator()).run(song.id)

    await _stage(db_session, storage, FakeSeparator(vocals=b"better vocals")).run(
        song.id
    )

    assets = await _assets(db_session, song.id)
    assert len(assets) == 3
    assert assets[AssetKind.VOCALS].size_bytes == len(b"better vocals")
    assert (
        await _read(storage, assets[AssetKind.VOCALS].storage_key) == b"better vocals"
    )


async def test_invalid_audio_produces_no_stems(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    separator = FakeSeparator()

    with pytest.raises(InvalidAudioError):
        await _stage(db_session, storage, separator, probe=invalid_probe).run(song.id)

    assert separator.calls == []
    assert set(await _assets(db_session, song.id)) == {AssetKind.ORIGINAL}


async def test_separator_failure_produces_no_stems(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)

    with pytest.raises(SeparationError):
        await _stage(db_session, storage, FakeSeparator(fail=True)).run(song.id)

    assert set(await _assets(db_session, song.id)) == {AssetKind.ORIGINAL}
    assert not await storage.exists(f"songs/{song.id}/vocals.flac")


async def test_missing_song_or_original_raises(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = _stage(db_session, storage, FakeSeparator())
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song = await SongRepository(db_session).add("No audio", "Artist")
    with pytest.raises(StageError, match="no original"):
        await stage.run(song.id)


async def test_database_failure_rolls_back_asset_registration(
    db_session: AsyncSession, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = await _song_with_original(db_session, storage)
    song_id = song.id  # instances are expired by the rollback
    stage = _stage(db_session, storage, FakeSeparator())
    calls = 0

    async def flaky_upsert(*args: object) -> SongAsset:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database went away")
        return await SongAssetRepository(db_session).upsert(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(stage._assets, "upsert", flaky_upsert)

    with pytest.raises(RuntimeError):
        await stage.run(song_id)

    assert set(await _assets(db_session, song_id)) == {AssetKind.ORIGINAL}


async def test_uses_the_song_preset(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    await SongRepository(db_session).set_separation_preset(
        song.id, SeparationPreset.ROFORMER
    )
    factory = FakeFactory(FakeSeparator())

    result = await _stage(db_session, storage, factory).run(song.id)

    assert factory.presets == [SeparationPreset.ROFORMER]
    assert result.preset is SeparationPreset.ROFORMER


async def test_override_preset_is_saved_on_success(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    factory = FakeFactory(FakeSeparator())

    await _stage(db_session, storage, factory).run(song.id, SeparationPreset.ROFORMER)

    assert factory.presets == [SeparationPreset.ROFORMER]
    refreshed = await db_session.get(Song, song.id)
    assert refreshed is not None
    assert refreshed.separation_preset is SeparationPreset.ROFORMER


async def test_override_preset_is_not_saved_on_failure(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_original(db_session, storage)
    song_id = song.id

    with pytest.raises(SeparationError):
        await _stage(db_session, storage, FakeSeparator(fail=True)).run(
            song_id, SeparationPreset.ROFORMER
        )

    db_session.expire_all()
    refreshed = await db_session.get(Song, song_id)
    assert refreshed is not None
    assert refreshed.separation_preset is SeparationPreset.DEMUCS


def test_build_separation_stage_builds_separators_from_settings(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, demucs_model="htdemucs_ft", demucs_shifts=3)

    stage = build_separation_stage(None, LocalStorage(tmp_path), settings)  # type: ignore[arg-type]

    demucs = stage._separator_factory(SeparationPreset.DEMUCS)
    roformer = stage._separator_factory(SeparationPreset.ROFORMER)
    assert isinstance(demucs, DemucsSeparator)
    assert demucs.name == "htdemucs_ft(shifts=3)"
    assert isinstance(roformer, RoformerSeparator)
