"""Pure functions relating timed words to the reference pitch curve."""

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from app.ml.transcription import TranscribedWord
from app.schemas.analysis import LyricLine, PitchCurve

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_note_name(midi: float) -> str:
    """Name the nearest note of a MIDI number, e.g. ``69.2`` -> ``A4``.

    Args:
        midi: Fractional MIDI note number.

    Returns:
        Note name with octave.
    """
    nearest = round(midi)
    return f"{NOTE_NAMES[nearest % 12]}{nearest // 12 - 1}"


def _frame_ranges(
    starts_ms: NDArray[np.int64], ends_ms: NDArray[np.int64], curve: PitchCurve
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Frame index ranges ``[first, last)`` covering each time span."""
    first = np.clip(np.ceil(starts_ms / curve.hop_ms), 0, curve.frame_count)
    last = np.clip(np.ceil(ends_ms / curve.hop_ms), first, curve.frame_count)
    return first.astype(np.int64), last.astype(np.int64)


def voiced_ratios(
    spans_ms: Sequence[tuple[int, int]], curve: PitchCurve, min_confidence: int
) -> NDArray[np.float64]:
    """Fraction of sung frames inside each time span.

    Args:
        spans_ms: ``(start_ms, end_ms)`` pairs.
        curve: Reference pitch curve.
        min_confidence: Confidence (0-100) from which a frame counts as sung.

    Returns:
        One ratio in [0, 1] per span; spans with no frame get 0.
    """
    if not spans_ms:
        return np.zeros(0)
    spans = np.asarray(spans_ms, dtype=np.int64)
    voiced = np.asarray(curve.confidence) >= min_confidence
    cumulative = np.concatenate(([0], np.cumsum(voiced, dtype=np.int64)))
    first, last = _frame_ranges(spans[:, 0], spans[:, 1], curve)
    counts = last - first
    sung = cumulative[last] - cumulative[first]
    ratios: NDArray[np.float64] = np.divide(
        sung, counts, out=np.zeros(len(spans), dtype=np.float64), where=counts > 0
    )
    return ratios


def find_unvoiced_words(
    words: Sequence[TranscribedWord],
    curve: PitchCurve,
    *,
    min_confidence: int,
    max_voiced_ratio: float,
    min_run_words: int = 3,
) -> list[int]:
    """Find phrases transcribed over no voice: likely hallucinations.

    A hallucination is a whole phrase invented over silence (e.g. "Gracias por
    ver el video", 5 words with no sung frame). Isolated words without voice
    are common in real lyrics, especially rap (short unvoiced words, small
    timing offsets), so only runs of at least ``min_run_words`` consecutive
    unvoiced words are reported.

    Args:
        words: Transcribed words in order.
        curve: Pitch curve of the isolated vocals.
        min_confidence: Confidence (0-100) from which a frame counts as sung.
        max_voiced_ratio: Words with a lower fraction of sung frames are
            unvoiced.
        min_run_words: Minimum consecutive unvoiced words to report them.

    Returns:
        Indexes of the words in suspicious runs.
    """
    ratios = voiced_ratios(
        [(word.start_ms, word.end_ms) for word in words], curve, min_confidence
    )
    unvoiced = np.concatenate(([0], (ratios < max_voiced_ratio).astype(np.int8), [0]))
    edges = np.diff(unvoiced)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    long_runs = (ends - starts) >= min_run_words
    return [
        index
        for start, end in zip(starts[long_runs], ends[long_runs], strict=True)
        for index in range(int(start), int(end))
    ]


class LinePitchStats(BaseModel):
    """Summary of the reference pitch of one lyric line, for human review.

    Attributes:
        index: Line index.
        text: Line text.
        voiced_ratio: Fraction of the line's frames that are sung.
        median_note: Median sung pitch as a note name, if any frame is sung.
        low_note: 10th percentile of the sung pitch.
        high_note: 90th percentile of the sung pitch.
    """

    index: int
    text: str
    voiced_ratio: float
    median_note: str | None
    low_note: str | None
    high_note: str | None


def line_pitch_stats(
    lines: Sequence[LyricLine], curve: PitchCurve, min_confidence: int
) -> list[LinePitchStats]:
    """Summarize the reference pitch of each line.

    Args:
        lines: Lyric lines.
        curve: Reference pitch curve.
        min_confidence: Confidence (0-100) from which a frame counts as sung.

    Returns:
        One summary per line.
    """
    pitch = curve.to_numpy(min_confidence=min_confidence)
    stats: list[LinePitchStats] = []
    for line in lines:
        segment = curve.slice_ms(line.start_ms, line.end_ms)
        first = math.ceil(line.start_ms / curve.hop_ms)
        sung = pitch[first : first + segment.frame_count]
        sung = sung[~np.isnan(sung)]
        ratio = sung.size / segment.frame_count if segment.frame_count else 0.0
        low, median, high = (
            np.percentile(sung, [10, 50, 90]).tolist() if sung.size else (None,) * 3
        )
        stats.append(
            LinePitchStats(
                index=line.index,
                text=line.text,
                voiced_ratio=round(ratio, 3),
                median_note=None if median is None else midi_to_note_name(median),
                low_note=None if low is None else midi_to_note_name(low),
                high_note=None if high is None else midi_to_note_name(high),
            )
        )
    return stats
