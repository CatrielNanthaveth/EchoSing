"""Score one sung lyric line against its reference pitch."""

from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import PitchCurve
from app.scoring.dtw import dtw
from app.scoring.pitch import (
    FloatArray,
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
    hop = settings.scoring_hop_ms

    reference_midi = resample(
        reference.to_numpy(min_confidence=settings.min_reference_confidence),
        reference.hop_ms,
        hop,
    )
    reference_weights = resample(reference.confidence_weights(), reference.hop_ms, hop)
    voiced = ~np.isnan(reference_midi)
    voiced_frames = int(np.count_nonzero(voiced))
    if voiced_frames * hop < settings.min_voiced_ms or voiced_frames == 0:
        return LineResult(
            scorable=False,
            score=None,
            accuracy=None,
            hit=False,
            voiced_frames=voiced_frames,
        )

    sung = resample(
        compensate_latency(hz_to_midi(np.asarray(sung_hz)), latency_ms, sung_hop_ms),
        sung_hop_ms,
        hop,
    )
    # Both curves start at the line start; once the latency is undone, singing
    # past the end of the line is dropped so both cover the same time span.
    sung = sung[: reference_midi.size]
    errors = _frame_errors(reference_midi, sung, settings)[voiced]

    credit = np.clip(
        (settings.zero_credit_semitones - errors)
        / (settings.zero_credit_semitones - settings.full_credit_semitones),
        0.0,
        1.0,
    )
    weights = reference_weights[voiced]
    if not weights.sum() > 0:
        weights = np.ones_like(weights)
    score = float(100.0 * np.average(credit, weights=weights))
    return LineResult(
        scorable=True,
        score=round(score, 2),
        accuracy=round(float(np.mean(errors <= settings.full_credit_semitones)), 4),
        hit=score >= settings.hit_threshold,
        voiced_frames=voiced_frames,
    )


def _frame_errors(
    reference: FloatArray, sung: FloatArray, config: ScoringConfig
) -> FloatArray:
    """Pitch error of each reference frame after DTW alignment.

    The whole reference timeline is aligned, pauses included, so both curves
    keep the same time scale and the warp limit is measured in real time.
    Unvoiced reference frames cost nothing; callers keep only voiced frames.
    """
    if sung.size == 0 or np.isnan(sung).all():
        return np.full(reference.size, config.max_error_semitones)
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
    return dtw(cost, band_ratio, config.step_penalty_semitones).row_costs
