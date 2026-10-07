import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.enums import SeparationPreset
from app.ml import separation
from app.ml.separation import DemucsSeparator, RoformerSeparator, SeparationError
from app.ml.tools import ToolError
from app.services.pipeline.separation import build_separator


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


def test_shifts_default_to_one_and_are_configurable() -> None:
    default = _separator().command(Path("song.mp3"), Path("out"))
    shifted = DemucsSeparator(shifts=5, python="py").command(
        Path("song.mp3"), Path("out")
    )

    assert default[default.index("--shifts") + 1] == "1"
    assert shifted[shifted.index("--shifts") + 1] == "5"


def test_name_describes_model_and_shifts() -> None:
    assert _separator().name == "htdemucs(shifts=1)"


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


# --- RoFormer (audio-separator) ----------------------------------------------


def _roformer() -> RoformerSeparator:
    return RoformerSeparator(
        model="melband_roformer_inst_v2.ckpt",
        models_dir=Path("models"),
        normalization=0.9,
        timeout_s=60,
        python="py",
    )


def test_roformer_command() -> None:
    command = _roformer().command(Path("in/song.mp3"), Path("out"))

    assert command[:2] == ["py", "-c"]
    assert "audio_separator.utils.cli" in command[2]
    assert command[3] == str(Path("in/song.mp3"))
    assert command[command.index("--model_filename") + 1] == (
        "melband_roformer_inst_v2.ckpt"
    )
    assert command[command.index("--model_file_dir") + 1] == "models"
    assert command[command.index("--output_dir") + 1] == "out"
    assert command[command.index("--output_format") + 1] == "FLAC"
    assert command[command.index("--normalization") + 1] == "0.9"
    names = json.loads(command[command.index("--custom_output_names") + 1])
    assert names == {"Vocals": "vocals", "Instrumental": "instrumental"}


def test_roformer_name_drops_the_weights_extension() -> None:
    assert _roformer().name == "melband_roformer_inst_v2"


async def test_roformer_returns_produced_stems(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        (tmp_path / "vocals.flac").write_bytes(b"v")
        (tmp_path / "instrumental.flac").write_bytes(b"i")
        return ""

    monkeypatch.setattr(separation, "run_tool", fake_run_tool)

    stems = await _roformer().separate(Path("song.mp3"), tmp_path)

    assert stems.vocals == tmp_path / "vocals.flac"
    assert stems.accompaniment == tmp_path / "instrumental.flac"


async def test_roformer_missing_stem_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        (tmp_path / "vocals.flac").write_bytes(b"v")
        return ""

    monkeypatch.setattr(separation, "run_tool", fake_run_tool)

    with pytest.raises(SeparationError, match="instrumental.flac"):
        await _roformer().separate(Path("song.mp3"), tmp_path)


async def test_roformer_tool_failure_raises_separation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def failing_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        raise ToolError("py failed", returncode=1, stderr_tail="model not found")

    monkeypatch.setattr(separation, "run_tool", failing_run_tool)

    with pytest.raises(SeparationError, match="model not found"):
        await _roformer().separate(Path("song.mp3"), tmp_path)


# --- build_separator ---------------------------------------------------------


def test_build_separator_maps_presets_to_configured_separators(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        ml_device="cpu",
        ml_models_dir=tmp_path,
        demucs_model="htdemucs_ft",
        demucs_shifts=3,
        roformer_model="custom_roformer.ckpt",
        roformer_normalization=1.0,
    )

    demucs = build_separator(SeparationPreset.DEMUCS, settings)
    roformer = build_separator(SeparationPreset.ROFORMER, settings)

    assert isinstance(demucs, DemucsSeparator)
    demucs_command = demucs.command(Path("a.mp3"), Path("out"))
    assert demucs_command[demucs_command.index("-n") + 1] == "htdemucs_ft"
    assert demucs_command[demucs_command.index("-d") + 1] == "cpu"
    assert demucs_command[demucs_command.index("--shifts") + 1] == "3"

    assert isinstance(roformer, RoformerSeparator)
    roformer_command = roformer.command(Path("a.mp3"), Path("out"))
    assert roformer_command[roformer_command.index("--model_filename") + 1] == (
        "custom_roformer.ckpt"
    )
    assert roformer_command[roformer_command.index("--model_file_dir") + 1] == str(
        tmp_path
    )
    assert roformer_command[roformer_command.index("--normalization") + 1] == "1.0"


def test_default_settings_match_the_chosen_presets() -> None:
    settings = Settings(_env_file=None)

    assert settings.default_separation_preset is SeparationPreset.DEMUCS
    assert build_separator(SeparationPreset.DEMUCS, settings).name == (
        "htdemucs(shifts=5)"
    )
    assert build_separator(SeparationPreset.ROFORMER, settings).name == (
        "model_bs_roformer_ep_317_sdr_12.9755"
    )
    assert settings.roformer_normalization == 0.9
