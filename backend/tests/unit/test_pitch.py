import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.ml import pitch
from app.ml.pitch import (
    PITCH_HOP_MS,
    CrepeExtractor,
    PitchExtractionError,
    RawPitch,
    hz_to_midi,
)
from app.ml.runners.crepe_runner import build_parser
from app.ml.tools import ToolError


def test_hz_to_midi_known_values() -> None:
    midi = hz_to_midi(np.array([440.0, 880.0, 220.0, 261.6256]))

    np.testing.assert_allclose(midi, [69.0, 81.0, 57.0, 60.0], atol=1e-4)


def test_hz_to_midi_marks_invalid_frequencies_as_nan() -> None:
    midi = hz_to_midi(np.array([0.0, -5.0, np.nan, np.inf, 440.0]))

    assert np.isnan(midi[:4]).all()
    assert midi[4] == 69.0


def test_raw_pitch_converts_to_stored_curve() -> None:
    raw = RawPitch(
        hop_ms=10, frequency_hz=[440.0, 0.0, 220.0], confidence=[0.9, 0.0, 0.456]
    )

    curve = raw.to_curve()

    assert curve.hop_ms == 10
    assert curve.midi == [69.0, None, 57.0]
    assert curve.confidence == [90, 0, 46]


@pytest.mark.parametrize(
    "data",
    [
        {"hop_ms": 10, "frequency_hz": [440.0], "confidence": []},
        {"hop_ms": 10, "frequency_hz": [440.0], "confidence": [1.5]},
        {"hop_ms": 10, "frequency_hz": [440.0], "confidence": [-0.1]},
        {"hop_ms": 0, "frequency_hz": [], "confidence": []},
    ],
)
def test_raw_pitch_rejects_invalid_output(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RawPitch.model_validate(data)


# --- CrepeExtractor ------------------------------------------------------------


def _extractor() -> CrepeExtractor:
    return CrepeExtractor(
        model="full",
        decoder="viterbi",
        fmin_hz=65.0,
        fmax_hz=1100.0,
        batch_size=512,
        device="cuda",
        timeout_s=60,
        python="py",
    )


def test_command_runs_the_crepe_runner() -> None:
    command = _extractor().command(Path("v.wav"), Path("out.json"))

    assert command[:5] == [
        "py",
        "-m",
        "app.ml.runners.crepe_runner",
        "v.wav",
        "out.json",
    ]
    assert command[command.index("--hop-ms") + 1] == str(PITCH_HOP_MS)
    assert command[command.index("--model") + 1] == "full"
    assert command[command.index("--decoder") + 1] == "viterbi"
    assert command[command.index("--fmin") + 1] == "65.0"
    assert command[command.index("--fmax") + 1] == "1100.0"
    assert command[command.index("--batch-size") + 1] == "512"
    assert command[command.index("--device") + 1] == "cuda"


def test_runner_command_matches_the_runner_arguments() -> None:
    command = _extractor().command(Path("v.wav"), Path("out.json"))

    args = build_parser().parse_args(command[3:])

    assert (args.audio, args.output, args.hop_ms) == ("v.wav", "out.json", 10)
    assert (args.model, args.decoder, args.batch_size) == ("full", "viterbi", 512)


def test_name_describes_model_and_decoder() -> None:
    assert _extractor().name == "torchcrepe-full-viterbi"


class FakeTools:
    def __init__(
        self, output: object | None = None, error: ToolError | None = None
    ) -> None:
        self.output = output
        self.error = error
        self.transcoded: list[tuple[Path, Path, int]] = []

    async def transcode(
        self, source: Path, destination: Path, sample_rate: int
    ) -> None:
        self.transcoded.append((source, destination, sample_rate))

    async def run_tool(self, args: Sequence[str | Path], *, timeout_s: float) -> str:
        if self.error is not None:
            raise self.error
        if self.output is not None:
            output = Path(str(args[4]))
            content = (
                self.output if isinstance(self.output, str) else json.dumps(self.output)
            )
            output.write_text(content, "utf-8")
        return ""


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> FakeTools:
    tools = FakeTools()
    monkeypatch.setattr(pitch, "transcode_to_wav", tools.transcode)
    monkeypatch.setattr(pitch, "run_tool", tools.run_tool)
    return tools


async def test_extract_decodes_runs_and_parses(
    fake_tools: FakeTools, tmp_path: Path
) -> None:
    fake_tools.output = {
        "hop_ms": 10,
        "frequency_hz": [440.0, 220.0],
        "confidence": [0.95, 0.1],
    }

    curve = await _extractor().extract(Path("vocals.flac"), tmp_path)

    assert fake_tools.transcoded == [
        (Path("vocals.flac"), tmp_path / "vocals_16k.wav", 16_000)
    ]
    assert curve.midi == [69.0, 57.0]
    assert curve.confidence == [95, 10]


async def test_extract_tool_failure(fake_tools: FakeTools, tmp_path: Path) -> None:
    fake_tools.error = ToolError("py failed", returncode=1, stderr_tail="CUDA OOM")

    with pytest.raises(PitchExtractionError, match="CUDA OOM"):
        await _extractor().extract(Path("vocals.flac"), tmp_path)


async def test_extract_missing_output(fake_tools: FakeTools, tmp_path: Path) -> None:
    with pytest.raises(PitchExtractionError, match="did not produce"):
        await _extractor().extract(Path("vocals.flac"), tmp_path)


async def test_extract_unreadable_output(fake_tools: FakeTools, tmp_path: Path) -> None:
    fake_tools.output = "not json"

    with pytest.raises(PitchExtractionError, match="Unreadable"):
        await _extractor().extract(Path("vocals.flac"), tmp_path)
