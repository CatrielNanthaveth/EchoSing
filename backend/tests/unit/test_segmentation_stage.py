import uuid
from pathlib import Path

import pytest

from app.cli import summarize
from app.ml.transcription import TranscribedWord, Transcription
from app.services.lyrics import SegmentationConfig
from app.services.pipeline.errors import StageError
from app.services.pipeline.segmentation import SegmentationStage, load_lines
from app.storage.keys import work_key
from app.storage.local import LocalStorage

SONG_ID = uuid.UUID("0e0b2cdf-45cb-48b0-8b06-e558286f0c18")


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _save_transcription(storage: LocalStorage) -> None:
    words = [
        TranscribedWord(text=text, start_ms=i * 400, end_ms=(i + 1) * 400)
        for i, text in enumerate(
            ["Dame", "de", "tu", "vida", "Que", "me", "obligue", "a", "renacer"]
        )
    ]
    transcription = Transcription(model="whisper-test", language="es", words=words)
    await storage.save(
        work_key(SONG_ID, "transcription.json"),
        transcription.model_dump_json().encode(),
        "application/json",
    )


async def test_segments_and_saves_lines(storage: LocalStorage) -> None:
    await _save_transcription(storage)

    result = await SegmentationStage(storage).run(SONG_ID)

    assert result.artifact_key == f"songs/{SONG_ID}/work/lines.json"
    assert result.lyrics.source == "transcription"
    assert [line.text for line in result.lyrics.lines] == [
        "Dame de tu vida",
        "Que me obligue a renacer",
    ]
    assert await load_lines(storage, SONG_ID) == result.lyrics


async def test_uses_the_given_config(storage: LocalStorage) -> None:
    await _save_transcription(storage)

    result = await SegmentationStage(storage, SegmentationConfig(max_line_words=3)).run(
        SONG_ID
    )

    assert all(len(line.words) <= 3 for line in result.lyrics.lines)


async def test_missing_transcription_raises(storage: LocalStorage) -> None:
    with pytest.raises(StageError, match="run the 'transcribe' stage first"):
        await SegmentationStage(storage).run(SONG_ID)


async def test_summary_lists_lines_with_times(storage: LocalStorage) -> None:
    await _save_transcription(storage)
    result = await SegmentationStage(storage).run(SONG_ID)

    summary = summarize(result).splitlines()

    assert summary[0].startswith("lines: 2")
    assert summary[1] == "  0 [0:00.00 - 0:01.60] Dame de tu vida"
    assert summary[2] == "  1 [0:01.60 - 0:03.60] Que me obligue a renacer"
