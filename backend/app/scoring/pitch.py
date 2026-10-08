"""Pitch curve utilities for scoring.

Curves are 1-D float arrays with one value per frame, frame ``i`` centered at
``i * hop_ms``, holding fractional MIDI note numbers (69.0 = A4 = 440 Hz) and
NaN where there is no voice. All functions are vectorized.
"""

from typing import Any

import numpy as np
from numpy.typing import NDArray

SEMITONES_PER_OCTAVE = 12.0

FloatArray = NDArray[np.float64]


def hz_to_midi(frequency_hz: NDArray[np.floating[Any]]) -> FloatArray:
    """Convert frequencies to fractional MIDI note numbers.

    ``midi = 69 + 12 * log2(f / 440)``: 440 Hz -> 69.0 (A4). Non-positive and
    non-finite frequencies become NaN (no voice).

    Args:
        frequency_hz: Frequencies in Hz.

    Returns:
        MIDI note numbers, same shape as the input.
    """
    frequency = np.asarray(frequency_hz, dtype=np.float64)
    valid = np.isfinite(frequency) & (frequency > 0)
    midi = np.full(frequency.shape, np.nan)
    midi[valid] = 69.0 + 12.0 * np.log2(frequency[valid] / 440.0)
    return midi


def resample(values: FloatArray, from_hop_ms: float, to_hop_ms: float) -> FloatArray:
    """Resample a curve to another frame rate by linear interpolation.

    An output frame is unvoiced (NaN) when it falls next to an unvoiced input
    frame, so silences are never bridged by interpolation.

    Args:
        values: Input curve (NaN = unvoiced).
        from_hop_ms: Time between input frames.
        to_hop_ms: Time between output frames.

    Returns:
        The curve sampled every ``to_hop_ms``, covering the same time span.

    Raises:
        ValueError: If a hop is not positive.
    """
    if from_hop_ms <= 0 or to_hop_ms <= 0:
        raise ValueError("Hop sizes must be positive")
    source = np.asarray(values, dtype=np.float64)
    if source.size == 0:
        return np.zeros(0)

    source_times = np.arange(source.size) * from_hop_ms
    count = int(np.floor(source_times[-1] / to_hop_ms + 1e-9)) + 1
    target_times = np.arange(count) * to_hop_ms

    voiced = ~np.isnan(source)
    filled = np.where(voiced, source, 0.0)
    result: FloatArray = np.interp(target_times, source_times, filled)

    left = np.clip(
        np.searchsorted(source_times, target_times + 1e-9, side="right") - 1,
        0,
        source.size - 1,
    )
    right = np.minimum(left + 1, source.size - 1)
    on_left_frame = np.isclose(target_times, source_times[left])
    unvoiced = ~voiced[left] | (~voiced[right] & ~on_left_frame)
    result[unvoiced] = np.nan
    return result


def compensate_latency(
    values: FloatArray, latency_ms: float, hop_ms: float
) -> FloatArray:
    """Undo the audio latency of a recorded curve.

    With a positive latency (e.g. Bluetooth headphones: the singer hears the
    music late, so they sing late), the first ``latency / hop`` frames are
    dropped so the curve lines up with the music again. A negative latency
    pads the start with unvoiced frames.

    Args:
        values: Recorded curve.
        latency_ms: Measured latency; positive means the voice arrives late.
        hop_ms: Time between frames.

    Returns:
        The aligned curve.

    Raises:
        ValueError: If the hop is not positive.
    """
    if hop_ms <= 0:
        raise ValueError("Hop size must be positive")
    curve = np.asarray(values, dtype=np.float64)
    frames = round(latency_ms / hop_ms)
    if frames >= 0:
        return curve[frames:].copy()
    return np.concatenate((np.full(-frames, np.nan), curve))


def semitone_error(
    sung: FloatArray, reference: FloatArray, *, octave_invariant: bool = True
) -> FloatArray:
    """Absolute pitch error in semitones, element-wise (broadcastable).

    With ``octave_invariant`` the error is taken modulo one octave, so singing
    an octave above or below the reference is not penalized; the error is
    then at most 6 semitones (a tritone). NaN in either input gives NaN.

    Args:
        sung: Sung pitch (MIDI).
        reference: Reference pitch (MIDI).
        octave_invariant: Whether to ignore whole-octave differences.

    Returns:
        Absolute errors in semitones.
    """
    difference = np.asarray(sung, dtype=np.float64) - np.asarray(
        reference, dtype=np.float64
    )
    if octave_invariant:
        half = SEMITONES_PER_OCTAVE / 2
        difference = np.mod(difference + half, SEMITONES_PER_OCTAVE) - half
    result: FloatArray = np.abs(difference)
    return result
