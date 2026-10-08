import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import summarize
from app.db.repositories.songs import SongRepository
from app.ml.transcription import TranscribedWord, Transcription
from app.services.lyrics import SegmentationConfig
from app.services.pipeline.errors import StageError
from app.services.pipeline.segmentation import SegmentationStage, load_lines
from app.storage.keys import work_key
from app.storage.local import LocalStorage

pytestmark = pytest.mark.integration

HEARD = ["Dame", "de", "tu", "vida", "Que", "me", "obligue", "a", "renacer"]


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _transcribed_song(
    session: AsyncSession, storage: LocalStorage, lyrics: str | None = None
) -> uuid.UUID:
    song = await SongRepository(session).add("Song", "Artist")
    if lyrics is not None:
        await SongRepository(session).set_lyrics(song.id, lyrics)
    words = [
        TranscribedWord(text=text, start_ms=i * 400, end_ms=(i + 1) * 400)
        for i, text in enumerate(HEARD)
    ]
    transcription = Transcription(model="whisper-test", language="es", words=words)
    await storage.save(
        work_key(song.id, "transcription.json"),
        transcription.model_dump_json().encode(),
        "application/json",
    )
    return song.id


async def test_without_lyrics_segments_the_transcription(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _transcribed_song(db_session, storage)

    result = await SegmentationStage(db_session, storage).run(song_id)

    assert result.artifact_key == f"songs/{song_id}/work/lines.json"
    assert result.lyrics.source == "transcription"
    assert result.lyrics.alignment is None
    assert [line.text for line in result.lyrics.lines] == [
        "Dame de tu vida",
        "Que me obligue a renacer",
    ]
    assert await load_lines(storage, song_id) == result.lyrics


async def test_with_lyrics_uses_the_official_text(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    lyrics = "[Verso]\nDame de tu vida, mi amor\n\nQue me obligue\na renacer\n"
    song_id = await _transcribed_song(db_session, storage, lyrics)

    result = await SegmentationStage(db_session, storage).run(song_id)

    assert result.lyrics.source == "official"
    assert [line.text for line in result.lyrics.lines] == [
        "Dame de tu vida, mi amor",
        "Que me obligue",
        "a renacer",
    ]
    report = result.lyrics.alignment
    assert report is not None
    assert report.matched_words == 9
    assert report.interpolated_words == 2  # "mi amor" was not transcribed


async def test_mismatching_lyrics_are_rejected(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _transcribed_song(
        db_session, storage, "Que se apague el día si me mientes"
    )

    with pytest.raises(StageError, match="Cannot use the lyrics"):
        await SegmentationStage(db_session, storage).run(song_id)

    assert not await storage.exists(work_key(song_id, "lines.json"))


async def test_uses_the_given_config(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _transcribed_song(db_session, storage)

    result = await SegmentationStage(
        db_session, storage, SegmentationConfig(max_line_words=3)
    ).run(song_id)

    assert all(len(line.words) <= 3 for line in result.lyrics.lines)


async def test_missing_song_or_transcription_raises(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    stage = SegmentationStage(db_session, storage)
    with pytest.raises(StageError, match="does not exist"):
        await stage.run(uuid.uuid4())

    song = await SongRepository(db_session).add("Not transcribed", "Artist")
    with pytest.raises(StageError, match="run the 'transcribe' stage first"):
        await stage.run(song.id)


async def test_summary_shows_source_alignment_and_timed_lines(
    db_session: AsyncSession, storage: LocalStorage
) -> None:
    song_id = await _transcribed_song(
        db_session, storage, "Dame de tu vida\nQue me obligue a renacer"
    )
    result = await SegmentationStage(db_session, storage).run(song_id)

    summary = summarize(result).splitlines()

    assert summary[0].startswith("source: official | lines: 2")
    assert summary[1].startswith("alignment: 9/9 words matched (100%)")
    assert summary[2] == "  0 [0:00.00 - 0:01.60] Dame de tu vida"
    assert summary[3] == "  1 [0:01.60 - 0:03.60] Que me obligue a renacer"
