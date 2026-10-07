import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Song
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.transcription import (
    TranscribedWord,
    Transcription,
    TranscriptionError,
    WhisperTranscriber,
)
from app.services.pipeline.errors import StageError
from app.services.pipeline.transcription import (
    TranscriptionStage,
    build_transcription_stage,
    load_transcription,
)
from app.storage.keys import asset_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration


class FakeTranscriber:
    def __init__(self, *, detected: str | None = "es", fail: bool = False) -> None:
        self.detected = detected
        self.fail = fail
        self.calls: list[tuple[bytes, str | None]] = []

    @property
    def name(self) -> str:
        return "fake-whisper"

    async def transcribe(
        self, audio: Path, output_dir: Path, language: str | None
    ) -> Transcription:
        self.calls.append((audio.read_bytes(), language))
        if self.fail:
            raise TranscriptionError("CUDA out of memory")
        return Transcription(
            model=self.name,
            language=language or self.detected,
            words=[
                TranscribedWord(
                    text="Dame", start_ms=19660, end_ms=20100, probability=0.95
                ),
                TranscribedWord(text="vida", start_ms=20420, end_ms=20620),
            ],
        )


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _song_with_vocals(
    session: AsyncSession, storage: LocalStorage, language: str | None = None
) -> Song:
    song = await SongRepository(session).add("Song", "Artist", language)
    stored = await storage.save(
        asset_key(song.id, AssetKind.VOCALS, "flac"), b"vocals-audio", "audio/flac"
    )
    await SongAssetRepository(session).add(song.id, AssetKind.VOCALS, stored)
    await session.commit()
    return song


async def test_saves_transcription_artifact(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_vocals(db_session, storage, language="es")
    transcriber = FakeTranscriber()

    result = await TranscriptionStage(db_session, storage, transcriber).run(song.id)

    assert transcriber.calls == [(b"vocals-audio", "es")]
    assert result.artifact_key == f"songs/{song.id}/work/transcription.json"
    assert result.transcription.text == "Dame vida"
    assert await load_transcription(storage, song.id) == result.transcription


async def test_detected_language_is_saved_when_unknown(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_vocals(db_session, storage, language=None)

    await TranscriptionStage(db_session, storage, FakeTranscriber(detected="pt")).run(
        song.id
    )

    refreshed = await db_session.get(Song, song.id)
    assert refreshed is not None
    assert refreshed.language == "pt"


async def test_known_language_is_not_overwritten(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_vocals(db_session, storage, language="es")

    await TranscriptionStage(db_session, storage, FakeTranscriber(detected="pt")).run(
        song.id
    )

    refreshed = await db_session.get(Song, song.id)
    assert refreshed is not None
    assert refreshed.language == "es"


async def test_failure_saves_nothing(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song = await _song_with_vocals(db_session, storage)

    with pytest.raises(TranscriptionError):
        await TranscriptionStage(db_session, storage, FakeTranscriber(fail=True)).run(
            song.id
        )

    assert not await storage.exists(f"songs/{song.id}/work/transcription.json")


async def test_missing_song_or_vocals_raises(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = TranscriptionStage(db_session, storage, FakeTranscriber())
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song = await SongRepository(db_session).add("Not separated", "Artist")
    with pytest.raises(StageError, match="run the 'separate' stage first"):
        await stage.run(song.id)


def test_build_transcription_stage_uses_settings(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, whisper_model="medium", ml_device="cpu")

    stage = build_transcription_stage(None, LocalStorage(tmp_path), settings)  # type: ignore[arg-type]

    transcriber = stage._transcriber
    assert isinstance(transcriber, WhisperTranscriber)
    assert transcriber.name == "whisper-medium"
    command = transcriber.command(Path("v.flac"), Path("out"), None)
    assert command[command.index("--device") + 1] == "cpu"
