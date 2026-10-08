"""Score one sung lyric line against its reference pitch."""

from typing import NamedTuple, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import PitchCurve
from app.scoring.dtw import BoolArray, DTWResult, dtw
from app.scoring.pitch import (
    FloatArray,
    bridge_gaps,
    compensate_latency,
    hz_to_midi,
    resample,
    semitone_error,
)


class ScoringConfig(BaseModel):
    """Tunable parameters of line scoring.

    Attributes:
        scoring_hop_ms: Frame period used to compare curves. Notes last at
            least ~100 ms, so 20 ms loses nothing for intonation and keeps DTW
            fast enough for real-time feedback.
        min_reference_confidence: Reference frames below this confidence
            (0-100) are not sung and not scored.
        min_voiced_ms: Lines with less sung reference than this (e.g. spoken
            passages) are not scorable.
        full_credit_semitones: Errors up to this get full credit (0.5 = 50
            cents, a quarter tone).
        zero_credit_semitones: Errors from this up get no credit; credit
            decreases linearly in between.
        max_error_semitones: Cap of the frame error; also the cost of a sung
            frame without voice.
        max_gap_ms: Unvoiced gaps of the sung curve up to this long, between
            voiced frames, are bridged before scoring: real-time detection
            drops frames inside notes, while the reference is smoothed.
        octave_invariant: Whether singing an octave above or below is right.
        max_warp_ms: How far (in time) the alignment may drift from the
            diagonal: enough to enter late or hold a note, not enough to match
            a neighboring note (None for no limit).
        step_penalty_semitones: Cost of each non-diagonal alignment step. It
            stops DTW from "rewarding" off-key singing by matching it to other
            reference notes of the same height (without it, singing 1.5
            semitones off scores 58 instead of 33). 2.0 gives the theoretical
            scores for detuned singing while keeping late entries (150 ms ->
            100) and rhythm variations (+-100 ms -> ~97) almost unpenalized.
        hit_threshold: Line score from which the line counts as a hit.
    """

    model_config = ConfigDict(frozen=True)

    scoring_hop_ms: float = Field(default=20.0, gt=0)
    min_reference_confidence: int = Field(default=50, ge=0, le=100)
    min_voiced_ms: float = Field(default=200.0, ge=0)
    full_credit_semitones: float = Field(default=0.5, ge=0)
    zero_credit_semitones: float = Field(default=2.0, gt=0)
    max_error_semitones: float = Field(default=6.0, gt=0)
    max_gap_ms: float = Field(default=100.0, ge=0)
    octave_invariant: bool = True
    max_warp_ms: float | None = Field(default=200.0, ge=0)
    step_penalty_semitones: float = Field(default=2.0, ge=0)
    hit_threshold: float = Field(default=60.0, ge=0, le=100)

    @model_validator(mode="after")
    def _check_credit_range(self) -> Self:
        if self.zero_credit_semitones <= self.full_credit_semitones:
            raise ValueError("zero_credit_semitones must exceed full_credit_semitones")
        return self


class LineResult(BaseModel):
    """Score of one sung line.

    Attributes:
        scorable: False when the reference has too little singing to judge.
        score: Weighted pitch score in [0, 100], None if not scorable.
        accuracy: Fraction of reference frames sung within full credit, in
            [0, 1], None if not scorable.
        hit: Whether the score reaches the hit threshold.
        voiced_frames: Sung reference frames, used to weight session totals.
    """

    scorable: bool
    score: float | None
    accuracy: float | None
    hit: bool
    voiced_frames: int


def score_line(
    reference: PitchCurve,
    sung_hz: FloatArray,
    sung_hop_ms: float,
    *,
    latency_ms: float = 0.0,
    config: ScoringConfig | None = None,
) -> LineResult:
    """Score a sung line against the reference pitch of that line.

    Both curves start at the line start. Clients should send a little more
    than the line (e.g. 300 ms) so the latency compensation has frames to
    shift in; anything past the line end is ignored.

    Steps: convert the singer's pitch to MIDI, undo the measured latency,
    resample both curves to ``scoring_hop_ms``, align them with DTW (so small
    rhythm differences are not penalized) and give each sung reference frame
    a credit from its pitch error. The line score is the mean credit weighted
    by the reference confidence, scaled to 0-100.

    Args:
        reference: Reference pitch of the line (MIDI + confidence).
        sung_hz: Singer's pitch in Hz per frame; 0 or NaN where unvoiced.
        sung_hop_ms: Time between the singer's frames.
        latency_ms: Measured audio latency to compensate.
        config: Scoring parameters.

    Returns:
        The line result.
    """
    settings = config or ScoringConfig()
    curves = prepare_curves(
        reference, sung_hz, sung_hop_ms, latency_ms=latency_ms, config=settings
    )
    if not curves.scorable:
        return LineResult(
            scorable=False,
            score=None,
            accuracy=None,
            hit=False,
            voiced_frames=curves.voiced_frames,
        )
    alignment = align_curves(curves.reference_midi, curves.sung, settings)
    return line_result(curves, frame_errors(curves, alignment, settings), settings)


class LineCurves(NamedTuple):
    """Reference and sung curves of a line on the scoring timeline.

    Attributes:
        reference_midi: Reference pitch per scoring frame, NaN where unvoiced.
        reference_weights: Confidence weight of each reference frame.
        sung: Sung pitch per scoring frame (latency undone, cropped to the
            line), NaN where unvoiced.
        min_voiced_ms: Sung reference needed to score the line.
        hop_ms: Scoring frame period.
    """

    reference_midi: FloatArray
    reference_weights: FloatArray
    sung: FloatArray
    min_voiced_ms: float
    hop_ms: float

    @property
    def voiced(self) -> BoolArray:
        """Mask of the reference frames that are sung."""
        mask: BoolArray = ~np.isnan(self.reference_midi)
        return mask

    @property
    def voiced_frames(self) -> int:
        """Number of sung reference frames."""
        return int(np.count_nonzero(self.voiced))

    @property
    def scorable(self) -> bool:
        """Whether the reference has enough singing to judge the line."""
        frames = self.voiced_frames
        return frames > 0 and frames * self.hop_ms >= self.min_voiced_ms


def prepare_curves(
    reference: PitchCurve,
    sung_hz: FloatArray,
    sung_hop_ms: float,
    *,
    latency_ms: float,
    config: ScoringConfig,
) -> LineCurves:
    """Put both curves of a line on the scoring timeline (see ``score_line``)."""
    hop = config.scoring_hop_ms
    reference_midi = resample(
        reference.to_numpy(min_confidence=config.min_reference_confidence),
        reference.hop_ms,
        hop,
    )
    sung = resample(
        compensate_latency(
            bridge_gaps(
                hz_to_midi(np.asarray(sung_hz)), sung_hop_ms, config.max_gap_ms
            ),
            latency_ms,
            sung_hop_ms,
        ),
        sung_hop_ms,
        hop,
    )
    # Both curves start at the line start; once the latency is undone, singing
    # past the end of the line is dropped so both cover the same time span.
    return LineCurves(
        reference_midi=reference_midi,
        reference_weights=resample(
            reference.confidence_weights(), reference.hop_ms, hop
        ),
        sung=sung[: reference_midi.size],
        min_voiced_ms=config.min_voiced_ms,
        hop_ms=hop,
    )


def align_curves(
    reference: FloatArray, sung: FloatArray, config: ScoringConfig
) -> DTWResult | None:
    """Align the sung curve to the reference with DTW.

    The whole reference timeline is aligned, pauses included, so both curves
    keep the same time scale and the warp limit is measured in real time.
    Unvoiced reference frames cost nothing.

    Returns:
        The alignment, or None if nothing was sung.
    """
    if sung.size == 0 or np.isnan(sung).all():
        return None
    cost = semitone_error(
        sung[None, :], reference[:, None], octave_invariant=config.octave_invariant
    )
    # Unvoiced sung frames cost the maximum, so DTW prefers sung ones.
    cost = np.where(
        np.isnan(cost),
        config.max_error_semitones,
        np.minimum(cost, config.max_error_semitones),
    )
    cost[np.isnan(reference)] = 0.0
    band_ratio = (
        None
        if config.max_warp_ms is None
        else config.max_warp_ms
        / (max(reference.size, sung.size) * config.scoring_hop_ms)
    )
    return dtw(cost, band_ratio, config.step_penalty_semitones)


def frame_errors(
    curves: LineCurves, alignment: DTWResult | None, config: ScoringConfig
) -> FloatArray:
    """Pitch error (semitones) of each sung reference frame after alignment."""
    if alignment is None:
        return np.full(curves.voiced_frames, config.max_error_semitones)
    errors: FloatArray = alignment.row_costs[curves.voiced]
    return errors


def frame_credit(errors: FloatArray, config: ScoringConfig) -> FloatArray:
    """Credit in [0, 1] of each frame from its pitch error."""
    credit: FloatArray = np.clip(
        (config.zero_credit_semitones - errors)
        / (config.zero_credit_semitones - config.full_credit_semitones),
        0.0,
        1.0,
    )
    return credit


def line_result(
    curves: LineCurves, errors: FloatArray, config: ScoringConfig
) -> LineResult:
    """Score a scorable line from the errors of its sung reference frames."""
    weights = curves.reference_weights[curves.voiced]
    if not weights.sum() > 0:
        weights = np.ones_like(weights)
    score = float(100.0 * np.average(frame_credit(errors, config), weights=weights))
    return LineResult(
        scorable=True,
        score=round(score, 2),
        accuracy=round(float(np.mean(errors <= config.full_credit_semitones)), 4),
        hit=score >= config.hit_threshold,
        voiced_frames=curves.voiced_frames,
    )
