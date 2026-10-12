"""Loudness envelope of an audio file (FFmpeg decodes, numpy measures)."""

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.ml.tools import run_tool_bytes
from app.schemas.analysis import LevelCurve

LEVEL_SAMPLE_RATE = 16_000
LEVEL_HOP_MS = 10
FLOOR_DB = -90.0
DECODE_TIMEOUT_S = 300.0


def level_curve(
    samples: NDArray[np.float32], sample_rate: int, hop_ms: int = LEVEL_HOP_MS
) -> LevelCurve:
    """RMS level in dBFS, one frame every ``hop_ms``.

    Frame ``i`` measures the window of one hop centered at ``i * hop_ms``,
    the same timing convention as the pitch curve.

    Args:
        samples: Mono samples in [-1, 1].
        sample_rate: Samples per second.
        hop_ms: Time between frames.

    Returns:
        The level curve, floored at -90 dBFS and rounded to 0.1 dB.
    """
    hop = sample_rate * hop_ms // 1000
    signal = np.asarray(samples, dtype=np.float64)
    # Pad half a hop in front so frame i is centered at i * hop.
    padded = np.concatenate((np.zeros(hop // 2), signal))
    frames = -(-padded.size // hop)
    padded = np.concatenate((padded, np.zeros(frames * hop - padded.size)))
    rms = np.sqrt(np.mean(padded.reshape(frames, hop) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 10 ** (FLOOR_DB / 20)))
    return LevelCurve(hop_ms=hop_ms, db=np.round(db, 1).tolist())


async def extract_level(audio: Path, hop_ms: int = LEVEL_HOP_MS) -> LevelCurve:
    """Loudness envelope of an audio file.

    FFmpeg decodes it to mono 32-bit float at 16 kHz on standard output.

    Args:
        audio: Audio file (e.g. the isolated vocals).
        hop_ms: Time between frames.

    Returns:
        The level curve.

    Raises:
        app.ml.tools.ToolError: If FFmpeg fails.
    """
    raw = await run_tool_bytes(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            audio,
            "-ac",
            "1",
            "-ar",
            str(LEVEL_SAMPLE_RATE),
            "-f",
            "f32le",
            "-",
        ],
        timeout_s=DECODE_TIMEOUT_S,
    )
    samples = np.frombuffer(raw, dtype="<f4")
    return level_curve(samples, LEVEL_SAMPLE_RATE, hop_ms)
