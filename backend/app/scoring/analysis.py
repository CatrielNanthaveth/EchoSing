"""Explain the score of a sung line: curves, alignment and offsets.

Used by the practice charts and the admin diagnostics. It runs exactly the
same steps as ``score_line``, so what is shown always matches the score.
"""

import numpy as np
from pydantic import BaseModel

from app.schemas.analysis import PitchCurve
from app.scoring.dtw import DTWResult
from app.scoring.line_score import (
    LineCurves,
    LineResult,
    ScoringConfig,
    align_curves,
    frame_credit,
    frame_errors,
    line_result,
    prepare_curves,
)
from app.scoring.pitch import SEMITONES_PER_OCTAVE, FloatArray


class LineAnalysis(BaseModel):
    """A sung line explained frame by frame, on the scoring timeline.

    Every list has one value per scoring frame from the line start; None marks
    frames without voice (or without a value).

    Attributes:
        result: The line score, identical to ``score_line``.
        hop_ms: Time between frames.
        reference_midi: Reference pitch.
        reference_weight: Confidence weight of each reference frame (0-1).
        sung_midi: What was sung at each moment (latency undone), shifted by
            whole octaves to the reference's register (``octave_shift``).
        aligned_midi: For each sung reference frame, the sung pitch DTW
            matched to it, in the reference's octave: what was scored.
        credit: Credit (0-1) of each sung reference frame.
        alignment_path: Pairs ``[reference_frame, sung_frame]`` of the
            alignment path.
        octave_shift: Whole octaves (in semitones) removed from ``sung_midi``,
            e.g. -12 when the line was sung an octave lower.
        timing_offset_ms: Median delay of the matched sung frames (positive:
            sung late), None if nothing was matched.
        pitch_offset_semitones: Median pitch error with sign (positive: sharp),
            None if nothing was matched.
    """

    result: LineResult
    hop_ms: float
    reference_midi: list[float | None]
    reference_weight: list[float]
    sung_midi: list[float | None]
    aligned_midi: list[float | None]
    credit: list[float | None]
    alignment_path: list[tuple[int, int]]
    octave_shift: int
    timing_offset_ms: float | None
    pitch_offset_semitones: float | None


def _to_list(values: FloatArray) -> list[float | None]:
    """Round to 2 decimals, NaN as None."""
    rounded = np.round(values, 2)
    return [None if np.isnan(value) else float(value) for value in rounded]


def _signed_error(
    sung: FloatArray, reference: FloatArray, octave_invariant: bool
) -> FloatArray:
    """Pitch error with sign (positive: sharp), folded into +-6 semitones."""
    difference = sung - reference
    if not octave_invariant:
        return difference
    half = SEMITONES_PER_OCTAVE / 2
    folded: FloatArray = np.mod(difference + half, SEMITONES_PER_OCTAVE) - half
    return folded


def _padded_sung(curves: LineCurves) -> FloatArray:
    """The sung curve over the whole line (it may stop before the end)."""
    sung = np.full(curves.reference_midi.size, np.nan)
    sung[: curves.sung.size] = curves.sung
    return sung


def _octave_shift(curves: LineCurves) -> int:
    """Whole octaves between what was sung and the reference (median)."""
    difference = _padded_sung(curves) - curves.reference_midi
    difference = difference[~np.isnan(difference)]
    if difference.size == 0:
        return 0
    octaves = round(float(np.median(difference)) / SEMITONES_PER_OCTAVE)
    return int(octaves * SEMITONES_PER_OCTAVE)


def analyze_line(
    reference: PitchCurve,
    sung_hz: FloatArray,
    sung_hop_ms: float,
    *,
    latency_ms: float = 0.0,
    config: ScoringConfig | None = None,
) -> LineAnalysis:
    """Score a line and explain how the score came out.

    Args:
        reference: Reference pitch of the line (MIDI + confidence).
        sung_hz: Singer's pitch in Hz per frame; 0 or NaN where unvoiced.
        sung_hop_ms: Time between the singer's frames.
        latency_ms: Measured audio latency to compensate.
        config: Scoring parameters.

    Returns:
        The analysis; offsets and alignment are empty when nothing was sung or
        the line is not scorable.
    """
    settings = config or ScoringConfig()
    curves = prepare_curves(
        reference, sung_hz, sung_hop_ms, latency_ms=latency_ms, config=settings
    )
    octave_shift = _octave_shift(curves)
    rows = curves.reference_midi.size
    aligned = np.full(rows, np.nan)
    credit = np.full(rows, np.nan)
    path: list[tuple[int, int]] = []
    timing: float | None = None
    pitch: float | None = None

    if curves.scorable:
        alignment = align_curves(curves.reference_midi, curves.sung, settings)
        errors = frame_errors(curves, alignment, settings)
        result = line_result(curves, errors, settings)
        credit[curves.voiced] = frame_credit(errors, settings)
        if alignment is not None:
            aligned, timing, pitch = _matched(curves, alignment, settings)
            path = [(int(i), int(j)) for i, j in np.argwhere(alignment.on_path)]
    else:
        result = LineResult(
            scorable=False,
            score=None,
            accuracy=None,
            hit=False,
            voiced_frames=curves.voiced_frames,
        )

    return LineAnalysis(
        result=result,
        hop_ms=settings.scoring_hop_ms,
        reference_midi=_to_list(curves.reference_midi),
        reference_weight=[round(float(w), 3) for w in curves.reference_weights],
        sung_midi=_to_list(_padded_sung(curves) - octave_shift),
        aligned_midi=_to_list(aligned),
        credit=_to_list(credit),
        alignment_path=path,
        octave_shift=octave_shift,
        timing_offset_ms=timing,
        pitch_offset_semitones=pitch,
    )


def _matched(
    curves: LineCurves, alignment: DTWResult, config: ScoringConfig
) -> tuple[FloatArray, float | None, float | None]:
    """Sung pitch matched to each reference frame, and the median offsets.

    For each reference frame, the path cell with the smallest pitch error is
    the one that was scored (``row_costs``); its sung frame gives the match.
    """
    reference, sung = curves.reference_midi, curves.sung
    signed = _signed_error(sung[None, :], reference[:, None], config.octave_invariant)
    candidates = np.where(alignment.on_path & ~np.isnan(signed), np.abs(signed), np.inf)
    best = candidates.argmin(axis=1)
    rows = np.arange(reference.size)
    matched = np.isfinite(candidates[rows, best]) & curves.voiced

    error = signed[rows, best]
    aligned: FloatArray = np.where(matched, reference + error, np.nan)
    if not matched.any():
        return aligned, None, None
    delay = (best[matched] - rows[matched]) * curves.hop_ms
    return (
        aligned,
        round(float(np.median(delay)), 1),
        round(float(np.median(error[matched])), 2),
    )
