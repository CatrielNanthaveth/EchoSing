from pathlib import Path

import pytest

from app.cli import build_parser, main


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
