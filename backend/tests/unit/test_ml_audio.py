import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.ml import audio
from app.ml.audio import InvalidAudioError, probe_duration_ms, transcode_to_mp3
from app.ml.tools import ToolError


class FakeRunTool:
    """Replaces ``run_tool``: records commands and returns a canned output."""

    def __init__(self, output: str = "", error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.commands: list[list[str]] = []

    async def __call__(self, args: Sequence[str | Path], *, timeout_s: float) -> str:
        self.commands.append([str(arg) for arg in args])
        if self.error is not None:
            raise self.error
        return self.output


def _probe(streams: list[str], duration: str | None) -> str:
    data: dict[str, object] = {"streams": [{"codec_type": s} for s in streams]}
    data["format"] = {} if duration is None else {"duration": duration}
    return json.dumps(data)


@pytest.fixture
def fake_tool(monkeypatch: pytest.MonkeyPatch) -> FakeRunTool:
    fake = FakeRunTool()
    monkeypatch.setattr(audio, "run_tool", fake)
    return fake


async def test_probe_returns_duration_in_ms(fake_tool: FakeRunTool) -> None:
    fake_tool.output = _probe(["video", "audio"], "245.3768")

    assert await probe_duration_ms(Path("song.mp3")) == 245377
    command = fake_tool.commands[0]
    assert command[0] == "ffprobe"
    assert command[-1] == "song.mp3"


@pytest.mark.parametrize(
    "output",
    [
        _probe(["video"], "10.0"),  # no audio stream
        _probe(["audio"], None),  # unknown duration
        _probe(["audio"], "0"),  # empty
        "not json",
        json.dumps({"streams": []}),  # missing format section
    ],
)
async def test_probe_rejects_invalid_outputs(
    fake_tool: FakeRunTool, output: str
) -> None:
    fake_tool.output = output

    with pytest.raises(InvalidAudioError):
        await probe_duration_ms(Path("song.mp3"))


async def test_probe_failure_means_invalid_audio(fake_tool: FakeRunTool) -> None:
    fake_tool.error = ToolError("ffprobe failed", returncode=1)

    with pytest.raises(InvalidAudioError):
        await probe_duration_ms(Path("lyrics.mp3"))


async def test_transcode_builds_ffmpeg_command(fake_tool: FakeRunTool) -> None:
    await transcode_to_mp3(Path("in.flac"), Path("out.mp3"), bitrate_kbps=160)

    command = fake_tool.commands[0]
    assert command[0] == "ffmpeg"
    assert command[command.index("-i") + 1] == "in.flac"
    assert command[command.index("-codec:a") + 1] == "libmp3lame"
    assert command[command.index("-b:a") + 1] == "160k"
    assert command[-1] == "out.mp3"
    assert "-y" in command


async def test_transcode_propagates_failures(fake_tool: FakeRunTool) -> None:
    fake_tool.error = ToolError("ffmpeg failed", returncode=1)

    with pytest.raises(ToolError):
        await transcode_to_mp3(Path("in.flac"), Path("out.mp3"))
