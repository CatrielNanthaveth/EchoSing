import shutil
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from app.ml import level as level_module
from app.ml.level import LEVEL_SAMPLE_RATE, extract_level, level_curve
from app.ml.tools import run_tool

RATE = 16_000


def test_level_of_a_full_scale_sine_is_minus_3_db() -> None:
    sine = np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE).astype(np.float32)

    curve = level_curve(sine, RATE)

    assert curve.hop_ms == 10
    assert curve.frame_count == 101  # 1 s plus the half-hop of centering
    assert np.median(curve.db) == pytest.approx(-3.0, abs=0.1)


def test_silence_is_floored() -> None:
    assert set(level_curve(np.zeros(RATE // 10, dtype=np.float32), RATE).db) == {-90.0}


def test_frames_are_centered_on_their_time() -> None:
    # A 10 ms burst starting at 100 ms: centered on frame 10 (105 ms).
    samples = np.zeros(RATE // 5, dtype=np.float32)
    samples[1600:1760] = 0.5

    db = level_curve(samples, RATE).db

    loudest = int(np.argmax(db))
    assert loudest in (10, 11)
    assert db[loudest] == pytest.approx(-6.0, abs=3.1)
    assert db[5] == -90.0


async def test_extract_level_decodes_with_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    sine = (
        0.5 * np.sin(2 * np.pi * 220 * np.arange(LEVEL_SAMPLE_RATE) / LEVEL_SAMPLE_RATE)
    ).astype("<f4")

    async def fake_run(args: Sequence[str | Path], *, timeout_s: float) -> bytes:
        commands.append([str(arg) for arg in args])
        return sine.tobytes()

    monkeypatch.setattr(level_module, "run_tool_bytes", fake_run)

    curve = await extract_level(Path("vocals.flac"))

    assert commands[0][:4] == ["ffmpeg", "-v", "error", "-i"]
    assert commands[0][-7:] == ["-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    assert np.median(curve.db) == pytest.approx(-9.0, abs=0.1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
async def test_extract_level_with_real_ffmpeg(tmp_path: Path) -> None:
    audio = tmp_path / "tone.wav"
    # FFmpeg's sine source has amplitude 1/8: -18 dBFS peak, -21 dBFS RMS.
    await run_tool(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            audio,
        ],
        timeout_s=60,
    )

    curve = await extract_level(audio)

    assert 99 <= curve.frame_count <= 102
    assert np.median(curve.db) == pytest.approx(-21.0, abs=0.3)
