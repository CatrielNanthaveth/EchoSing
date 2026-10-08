import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import summarize
from app.core.config import Settings
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.pitch import CrepeExtractor, PitchExtractionError
from app.ml.transcription import TranscribedWord, Transcription
from app.schemas.analysis import LyricLine, PitchCurve, Word
from app.services.pipeline.errors import StageError
from app.services.pipeline.pitch import PitchStage, build_pitch_stage, load_pitch
from app.services.pipeline.segmentation import SegmentedLyrics
from app.services.pipeline.transcription import load_transcription
from app.storage.keys import asset_key, work_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

# 3 s of audio: sung (A3) during the first 2 s, silence afterwards.
FRAMES = 300
SUNG_FRAMES = 200


def synthetic_curve() -> PitchCurve:
    midi = np.full(FRAMES, 57.0) + 0.1 * np.sin(np.arange(FRAMES) / 5)
    confidence = np.where(np.arange(FRAMES) < SUNG_FRAMES, 0.9, 0.0)
    return PitchCurve.from_numpy(midi, confidence, 10)


class FakeExtractor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.audio: bytes | None = None

    @property
    def name(self) -> str:
        return "fake-crepe"

    async def extract(self, audio: Path, work_dir: Path) -> PitchCurve:
        self.audio = audio.read_bytes()
        if self.fail:
            raise PitchExtractionError("CUDA out of memory")
        return synthetic_curve()


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


async def _save_transcription(storage: LocalStorage, song_id: uuid.UUID) -> None:
    sung = [("te", 0, 600), ("puedo", 600, 1200), ("enamorar", 1200, 2000)]
    outro = [("Gracias", 2100, 2300), ("por", 2300, 2500), ("ver.", 2500, 2900)]
    words = [TranscribedWord(text=t, start_ms=s, end_ms=e) for t, s, e in sung + outro]
    transcription = Transcription(model="whisper-test", language="es", words=words)
    await storage.save(
        work_key(song_id, "transcription.json"),
        transcription.model_dump_json().encode(),
        "application/json",
    )


async def _save_lines(storage: LocalStorage, song_id: uuid.UUID) -> None:
    lines = [
        LyricLine(
            index=0,
            start_ms=0,
            end_ms=2000,
            text="te puedo enamorar",
            words=[Word(text="te puedo enamorar", start_ms=0, end_ms=2000)],
        )
    ]
    await storage.save(
        work_key(song_id, "lines.json"),
        SegmentedLyrics(source="transcription", lines=lines).model_dump_json().encode(),
        "application/json",
    )


async def test_saves_the_pitch_curve(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    extractor = FakeExtractor()

    result = await PitchStage(db_session, storage, extractor).run(song_id)

    assert extractor.audio == b"vocals-audio"
    assert result.artifact_key == f"songs/{song_id}/work/pitch.json"
    assert result.extractor == "fake-crepe"
    assert result.frame_count == FRAMES
    assert result.voiced_ratio == pytest.approx(SUNG_FRAMES / FRAMES)
    assert await load_pitch(storage, song_id) == synthetic_curve()
    assert result.unvoiced_words == []
    assert result.line_stats == []


async def test_hallucinated_phrase_is_discarded_from_the_transcription(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    await _save_transcription(storage, song_id)

    result = await PitchStage(db_session, storage, FakeExtractor()).run(song_id)

    assert [w.text for w in result.unvoiced_words] == ["Gracias", "por", "ver."]
    assert result.unvoiced_words_discarded is True
    transcription = await load_transcription(storage, song_id)
    assert transcription.text == "te puedo enamorar"
    assert [w.text for w in transcription.discarded] == ["Gracias", "por", "ver."]


async def test_report_only_leaves_the_transcription_untouched(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    await _save_transcription(storage, song_id)

    result = await PitchStage(
        db_session, storage, FakeExtractor(), discard_unvoiced_words=False
    ).run(song_id)

    assert len(result.unvoiced_words) == 3
    assert result.unvoiced_words_discarded is False
    transcription = await load_transcription(storage, song_id)
    assert len(transcription.words) == 6
    assert transcription.discarded == []


async def test_line_stats_when_lines_exist(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    await _save_lines(storage, song_id)

    result = await PitchStage(db_session, storage, FakeExtractor()).run(song_id)

    assert len(result.line_stats) == 1
    assert result.line_stats[0].voiced_ratio == 1.0
    assert result.line_stats[0].median_note == "A3"


async def test_extraction_failure_saves_nothing(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)

    with pytest.raises(PitchExtractionError):
        await PitchStage(db_session, storage, FakeExtractor(fail=True)).run(song_id)

    assert not await storage.exists(work_key(song_id, "pitch.json"))


async def test_missing_song_or_vocals_raises(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = PitchStage(db_session, storage, FakeExtractor())
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song = await SongRepository(db_session).add("Not separated", "Artist")
    with pytest.raises(StageError, match="run the 'separate' stage first"):
        await stage.run(song.id)


async def test_summary_shows_curve_findings_and_lines(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _song_with_vocals(db_session, storage)
    await _save_transcription(storage, song_id)
    await _save_lines(storage, song_id)
    result = await PitchStage(db_session, storage, FakeExtractor()).run(song_id)

    summary = summarize(result).splitlines()

    assert summary[0].startswith("extractor: fake-crepe | frames: 300 | sung: 67%")
    assert summary[1] == (
        "words sung over no voice (discarded): Gracias@2.10s por@2.30s ver.@2.50s"
    )
    assert summary[2] == "  0 sung 100%   A3 [A3..A3]  te puedo enamorar"


def test_build_pitch_stage_uses_settings(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        crepe_model="tiny",
        crepe_decoder="argmax",
        ml_device="cpu",
        hallucination_voicing_filter=False,
    )

    stage = build_pitch_stage(None, LocalStorage(tmp_path), settings)  # type: ignore[arg-type]

    extractor = stage._extractor
    assert isinstance(extractor, CrepeExtractor)
    assert extractor.name == "torchcrepe-tiny-argmax"
    command = extractor.command(Path("v.wav"), Path("o.json"))
    assert command[command.index("--device") + 1] == "cpu"
    assert stage._discard_unvoiced_words is False
