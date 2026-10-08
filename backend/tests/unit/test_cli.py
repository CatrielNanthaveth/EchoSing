import uuid
from pathlib import Path

import pytest

from app.cli import build_parser, main, summarize
from app.domain.enums import IngestionStage, SeparationPreset, SongStatus
from app.ml.transcription import TranscribedWord, Transcription
from app.services.pipeline.transcription import TranscriptionResult
from app.services.song_ingestion import SongRegistration


def test_add_song_arguments_are_parsed() -> None:
    args = build_parser().parse_args(
        ["add-song", "song.mp3", "--title", "T", "--artist", "A", "--language", "es"]
    )

    assert args.command == "add-song"
    assert args.path == Path("song.mp3")
    assert (args.title, args.artist, args.language) == ("T", "A", "es")


def test_title_and_artist_are_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["add-song", "song.mp3", "--title", "T"])


def test_missing_file_fails_without_touching_services(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.mp3"

    exit_code = main(["add-song", str(missing), "--title", "T", "--artist", "A"])

    assert exit_code == 1
    assert "File not found" in capsys.readouterr().err


def test_separator_option_is_parsed_as_preset() -> None:
    parser = build_parser()

    add_song = parser.parse_args(
        [
            "add-song",
            "s.mp3",
            "--title",
            "T",
            "--artist",
            "A",
            "--separator",
            "roformer",
        ]
    )
    run_stage = parser.parse_args(
        ["run-stage", "separate", "0e0b2cdf-45cb-48b0-8b06-e558286f0c18"]
    )

    assert add_song.separator is SeparationPreset.ROFORMER
    assert run_stage.separator is None


def test_unknown_separator_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["add-song", "s.mp3", "--title", "T", "--artist", "A", "--separator", "x"]
        )


def test_separator_only_applies_to_separate_stage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "run-stage",
                "transcribe",
                "0e0b2cdf-45cb-48b0-8b06-e558286f0c18",
                "--separator",
                "demucs",
            ]
        )

    assert "--separator only applies" in capsys.readouterr().err


def test_summarize_transcription_shows_text_and_first_words() -> None:
    result = TranscriptionResult(
        song_id=uuid.UUID("0e0b2cdf-45cb-48b0-8b06-e558286f0c18"),
        artifact_key="songs/x/work/transcription.json",
        transcription=Transcription(
            model="whisper-large-v3-turbo",
            language="es",
            words=[
                TranscribedWord(text="Dame", start_ms=19660, end_ms=20100),
                TranscribedWord(text="vida", start_ms=20420, end_ms=20620),
            ],
        ),
    )

    summary = summarize(result)

    assert "language: es" in summary
    assert "words: 2" in summary
    assert "Dame@19.66s" in summary
    assert summary.endswith("Dame vida")


def test_summarize_other_results_as_json() -> None:
    registration = SongRegistration(
        song_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        status=SongStatus.PENDING,
        stage=IngestionStage.QUEUED,
        separation_preset=SeparationPreset.DEMUCS,
    )

    assert '"status": "pending"' in summarize(registration)


def test_lyrics_options_are_parsed() -> None:
    parser = build_parser()

    add_song = parser.parse_args(
        ["add-song", "s.mp3", "--title", "T", "--artist", "A", "--lyrics", "l.txt"]
    )
    set_lyrics = parser.parse_args(
        ["set-lyrics", "0e0b2cdf-45cb-48b0-8b06-e558286f0c18", "l.txt"]
    )

    assert add_song.lyrics == Path("l.txt")
    assert set_lyrics.path == Path("l.txt")


@pytest.mark.parametrize("command", ["add-song", "set-lyrics"])
def test_missing_lyrics_file_fails_without_touching_services(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    missing = tmp_path / "missing.txt"
    argv = (
        [
            "add-song",
            str(audio),
            "--title",
            "T",
            "--artist",
            "A",
            "--lyrics",
            str(missing),
        ]
        if command == "add-song"
        else ["set-lyrics", "0e0b2cdf-45cb-48b0-8b06-e558286f0c18", str(missing)]
    )

    assert main(argv) == 1
    assert "File not found" in capsys.readouterr().err


def test_pipeline_commands_are_parsed() -> None:
    parser = build_parser()
    song_id = "0e0b2cdf-45cb-48b0-8b06-e558286f0c18"

    assert parser.parse_args(["run-pipeline", song_id]).song_id == uuid.UUID(song_id)
    assert parser.parse_args(["requeue", song_id]).command == "requeue"
    assert parser.parse_args(["run-stage", "persist", song_id]).stage == "persist"
