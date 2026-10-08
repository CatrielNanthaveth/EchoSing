"""Audio inspection and conversion through FFmpeg (``ffprobe``/``ffmpeg`` CLIs)."""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.ml.tools import ToolError, run_tool

PROBE_TIMEOUT_S = 60.0
TRANSCODE_TIMEOUT_S = 600.0


class InvalidAudioError(Exception):
    """The file is not a readable audio file."""


class _ProbeStream(BaseModel):
    codec_type: str


class _ProbeFormat(BaseModel):
    duration: float | None = None


class _ProbeOutput(BaseModel):
    streams: list[_ProbeStream] = []
    format: _ProbeFormat


async def probe_duration_ms(path: Path) -> int:
    """Validate that a file contains audio and return its duration.

    Args:
        path: File to inspect.

    Returns:
        Duration in milliseconds.

    Raises:
        InvalidAudioError: If FFmpeg cannot read the file, it has no audio
            stream or its duration is unknown.
    """
    try:
        output = await run_tool(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                path,
            ],
            timeout_s=PROBE_TIMEOUT_S,
        )
        probe = _ProbeOutput.model_validate(json.loads(output))
    except (ToolError, ValueError, ValidationError) as error:
        raise InvalidAudioError(f"Not a readable audio file: {path.name}") from error

    if not any(stream.codec_type == "audio" for stream in probe.streams):
        raise InvalidAudioError(f"No audio stream in {path.name}")
    duration = probe.format.duration
    if duration is None or duration <= 0:
        raise InvalidAudioError(f"Unknown duration for {path.name}")
    return round(duration * 1000)


async def transcode_to_mp3(
    source: Path, destination: Path, bitrate_kbps: int = 192
) -> None:
    """Encode an audio file as MP3 for streaming to clients.

    Args:
        source: Input audio file.
        destination: Output MP3 file (overwritten if it exists).
        bitrate_kbps: Constant bitrate of the output.

    Raises:
        ToolError: If FFmpeg fails.
    """
    await run_tool(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            source,
            "-vn",
            "-map_metadata",
            "-1",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate_kbps}k",
            destination,
        ],
        timeout_s=TRANSCODE_TIMEOUT_S,
    )


async def transcode_to_wav(
    source: Path, destination: Path, sample_rate: int = 16_000
) -> None:
    """Decode an audio file to mono 16-bit PCM WAV, e.g. for pitch models.

    Args:
        source: Input audio file.
        destination: Output WAV file (overwritten if it exists).
        sample_rate: Output sample rate in Hz.

    Raises:
        ToolError: If FFmpeg fails.
    """
    await run_tool(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            destination,
        ],
        timeout_s=TRANSCODE_TIMEOUT_S,
    )
