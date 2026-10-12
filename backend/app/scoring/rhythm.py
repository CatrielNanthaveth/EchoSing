"""Rhythm scoring (rap mode): when each syllable is hit, ignoring pitch.

Syllable attacks are sudden rises in loudness. Unlike voicing, loudness also
rises on unvoiced consonants ("t", "k", "ch"), which carry the rhythm of rap.
The same detector runs on the reference vocals' level curve and on the
singer's microphone level, so both sides are comparable.
"""

from typing import Self

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import LevelCurve
from app.scoring.line_score import LineResult
from app.scoring.pitch import FloatArray, compensate_latency, resample

SILENT_DB = -90.0


class RhythmConfig(BaseModel):
    """Tunable parameters of rhythm scoring.

    Detector defaults were chosen on the reference vocals of real songs: ~0.8
    attacks per sung syllable (merged syllables have no dip), 170-210 ms apart
    in rap.

    Attributes:
        rise_db: An attack rises at least this much over the quietest level
            of the preceding ``rise_window_ms``.
        rise_window_ms: Window the rise is measured against.
        floor_below_peak_db: Attacks must reach the line's loudest level minus
            this (independent of the microphone gain).
        absolute_floor_db: ...and at least this level (silence is no attack).
        refractory_ms: Minimum time between attacks.
        full_credit_ms: Attacks off by up to this get full credit.
        zero_credit_ms: Attacks off by this or more get none; also the farthest
            two attacks can be paired.
        min_onsets: Lines with fewer reference attacks are not scorable.
        hit_threshold: Line score from which the line counts as a hit.
    """

    model_config = ConfigDict(frozen=True)

    rise_db: float = Field(default=6.0, gt=0)
    rise_window_ms: float = Field(default=50.0, gt=0)
    floor_below_peak_db: float = Field(default=30.0, gt=0)
    absolute_floor_db: float = Field(default=-55.0, le=0)
    refractory_ms: float = Field(default=100.0, ge=0)
    full_credit_ms: float = Field(default=40.0, ge=0)
    zero_credit_ms: float = Field(default=100.0, gt=0)
    min_onsets: int = Field(default=3, ge=1)
    hit_threshold: float = Field(default=60.0, ge=0, le=100)

    @model_validator(mode="after")
    def _check_credit_range(self) -> Self:
        if self.zero_credit_ms <= self.full_credit_ms:
            raise ValueError("zero_credit_ms must exceed full_credit_ms")
        return self


class OnsetPair(BaseModel):
    """A reference attack and the sung attack matched to it.

    Attributes:
        reference: Index of the reference attack.
        sung: Index of the sung attack.
        offset_ms: Sung minus reference time (positive: late).
        credit: Credit of the pair, 0-1.
    """

    reference: int
    sung: int
    offset_ms: float
    credit: float


class RhythmAnalysis(BaseModel):
    """A line scored by rhythm, explained attack by attack.

    Times are in ms from the line start (the sung ones with latency undone).

    Attributes:
        result: The line score.
        reference_onsets_ms: Syllable attacks of the original.
        sung_onsets_ms: Syllable attacks of the singer (up to the matching
            reach past the line end).
        pairs: Matched attacks, in order.
        missed: Reference attacks with no sung match.
        extra: Sung attacks inside the line with no reference match.
        timing_offset_ms: Median offset of the pairs (positive: late), None
            without pairs.
    """

    result: LineResult
    reference_onsets_ms: list[float]
    sung_onsets_ms: list[float]
    pairs: list[OnsetPair]
    missed: int
    extra: int
    timing_offset_ms: float | None


def level_onsets(db: FloatArray, hop_ms: float, config: RhythmConfig) -> FloatArray:
    """Times (ms) of the attacks of a level curve.

    An attack is a local maximum of the rise (level minus the quietest level
    of the preceding window) above ``rise_db``, loud enough for both floors,
    at least ``refractory_ms`` after the previous attack.

    Args:
        db: Level per frame (dBFS).
        hop_ms: Time between frames.
        config: Detector parameters.

    Returns:
        Attack times, ascending.
    """
    level = np.asarray(db, dtype=np.float64)
    if level.size == 0:
        return np.zeros(0)
    lag = max(1, round(config.rise_window_ms / hop_ms))
    padded = np.concatenate((np.full(lag, level[0]), level))
    rise = level - sliding_window_view(padded[:-1], lag).min(axis=1)
    floor = max(level.max() - config.floor_below_peak_db, config.absolute_floor_db)
    before = np.concatenate(([-np.inf], rise[:-1]))
    after = np.concatenate((rise[1:], [-np.inf]))
    peaks = (
        (rise >= config.rise_db) & (level >= floor) & (rise >= before) & (rise > after)
    )

    times: list[float] = []
    for frame in np.flatnonzero(peaks):  # attacks are few: a plain loop is fine
        time = float(frame * hop_ms)
        if not times or time - times[-1] >= config.refractory_ms:
            times.append(time)
    return np.asarray(times, dtype=np.float64)


def _match(
    reference: FloatArray, sung: FloatArray, config: RhythmConfig
) -> list[tuple[int, int, float]]:
    """Pair attacks one to one, in order, maximizing the total credit.

    A weighted longest common subsequence: each row is filled with numpy (the
    best score taking pair ``(i, j)`` or skipping reference attack ``i``, then
    a running maximum along the sung attacks).

    Returns:
        ``(reference index, sung index, credit)`` for each pair with credit.
    """
    offset = np.abs(sung[None, :] - reference[:, None])
    credit = np.clip(
        (config.zero_credit_ms - offset)
        / (config.zero_credit_ms - config.full_credit_ms),
        0.0,
        1.0,
    )
    rows, columns = credit.shape
    best = np.zeros((rows + 1, columns + 1))
    for i in range(rows):
        take = np.where(credit[i] > 0, best[i, :-1] + credit[i], 0.0)
        best[i + 1, 1:] = np.maximum.accumulate(np.maximum(best[i, 1:], take))

    pairs: list[tuple[int, int, float]] = []
    i, j = rows, columns
    while i > 0 and j > 0:
        value = float(credit[i - 1, j - 1])
        if value > 0 and np.isclose(best[i, j], best[i - 1, j - 1] + value):
            pairs.append((i - 1, j - 1, value))
            i, j = i - 1, j - 1
        elif np.isclose(best[i, j], best[i - 1, j]):
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def analyze_rhythm(
    reference: LevelCurve,
    sung_db: FloatArray,
    sung_hop_ms: float,
    *,
    latency_ms: float = 0.0,
    config: RhythmConfig | None = None,
) -> RhythmAnalysis:
    """Score a line by the timing of its syllable attacks and explain it.

    Both curves start at the line start; the sung one may run past the end
    (clients send ~300 ms more), and attacks there can still match late.

    Attacks are paired by proximity, so an offset beyond half the time between
    syllables reads as the neighboring syllable: in fast rap, being a whole
    syllable late can look on time. Phrase starts after a pause are unambiguous.

    Args:
        reference: Level of the reference vocals over the line.
        sung_db: Singer's microphone level per frame (dBFS).
        sung_hop_ms: Time between the singer's frames.
        latency_ms: Measured audio latency to compensate.
        config: Rhythm parameters.

    Returns:
        The analysis, including the line result.
    """
    settings = config or RhythmConfig()
    hop = reference.hop_ms
    reference_db = np.asarray(reference.db, dtype=np.float64)
    line_ms = reference_db.size * hop
    shifted = compensate_latency(
        np.asarray(sung_db, dtype=np.float64), latency_ms, sung_hop_ms
    )
    sung_level = np.nan_to_num(resample(shifted, sung_hop_ms, hop), nan=SILENT_DB)

    reference_onsets = level_onsets(reference_db, hop, settings)
    sung_onsets = level_onsets(sung_level, hop, settings)
    sung_onsets = sung_onsets[sung_onsets < line_ms + settings.zero_credit_ms]
    attacks = int(reference_onsets.size)

    if attacks < settings.min_onsets:
        return RhythmAnalysis(
            result=LineResult(
                scorable=False,
                score=None,
                accuracy=None,
                hit=False,
                voiced_frames=attacks,
            ),
            reference_onsets_ms=reference_onsets.tolist(),
            sung_onsets_ms=sung_onsets.tolist(),
            pairs=[],
            missed=0,
            extra=0,
            timing_offset_ms=None,
        )

    matched = _match(reference_onsets, sung_onsets, settings)
    paired = {j for _, j, _ in matched}
    extra = sum(
        1 for j, time in enumerate(sung_onsets) if j not in paired and time < line_ms
    )
    score = 100.0 * sum(credit for _, _, credit in matched) / (attacks + extra)
    pairs = [
        OnsetPair(
            reference=i,
            sung=j,
            offset_ms=round(float(sung_onsets[j] - reference_onsets[i]), 1),
            credit=round(credit, 3),
        )
        for i, j, credit in matched
    ]
    on_time = sum(1 for pair in pairs if abs(pair.offset_ms) <= settings.full_credit_ms)
    return RhythmAnalysis(
        result=LineResult(
            scorable=True,
            score=round(score, 2),
            accuracy=round(on_time / attacks, 4),
            hit=score >= settings.hit_threshold,
            # Weight of the line in the session totals: its attacks.
            voiced_frames=attacks,
        ),
        reference_onsets_ms=reference_onsets.tolist(),
        sung_onsets_ms=sung_onsets.tolist(),
        pairs=pairs,
        missed=attacks - len(pairs),
        extra=extra,
        timing_offset_ms=(
            round(float(np.median([pair.offset_ms for pair in pairs])), 1)
            if pairs
            else None
        ),
    )
