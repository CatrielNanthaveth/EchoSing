from collections.abc import Sequence
from pathlib import Path

import pytest

from app.ml import separation
from app.ml.separation import DemucsSeparator, SeparationError
from app.ml.tools import ToolError


def _separator() -> DemucsSeparator:
    return DemucsSeparator(model="htdemucs", device="cuda", timeout_s=60, python="py")


def test_command_runs_two_stem_flac_separation() -> None:
    command = _separator().command(Path("in/song.mp3"), Path("out"))

    assert command[:3] == ["py", "-m", "demucs"]
    assert command[command.index("-n") + 1] == "htdemucs"
    assert command[command.index("-d") + 1] == "cuda"
    assert command[command.index("--two-stems") + 1] == "vocals"
    assert "--flac" in command
    assert command[command.index("-o") + 1] == "out"
    assert command[command.index("--filename") + 1] == "{stem}.{ext}"
    assert command[-1] == str(Path("in/song.mp3"))


def test_name_is_the_model() -> None:
    assert _separator().name == "htdemucs"


async def test_separate_returns_produced_stems(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        stems_dir = tmp_path / "htdemucs"
        stems_dir.mkdir()
        (stems_dir / "vocals.flac").write_bytes(b"v")
        (stems_dir / "no_vocals.flac").write_bytes(b"i")
        return ""

    monkeypatch.setattr(separation, "run_tool", fake_run_tool)

    stems = await _separator().separate(Path("song.mp3"), tmp_path)

    assert stems.vocals == tmp_path / "htdemucs" / "vocals.flac"
    assert stems.accompaniment == tmp_path / "htdemucs" / "no_vocals.flac"


async def test_missing_stem_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        (tmp_path / "htdemucs").mkdir()
        (tmp_path / "htdemucs" / "vocals.flac").write_bytes(b"v")
        return ""

    monkeypatch.setattr(separation, "run_tool", fake_run_tool)

    with pytest.raises(SeparationError, match="no_vocals.flac"):
        await _separator().separate(Path("song.mp3"), tmp_path)


async def test_tool_failure_raises_separation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def failing_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        raise ToolError("python failed", returncode=1, stderr_tail="CUDA out of memory")

    monkeypatch.setattr(separation, "run_tool", failing_run_tool)

    with pytest.raises(SeparationError, match="CUDA out of memory"):
        await _separator().separate(Path("song.mp3"), tmp_path)
