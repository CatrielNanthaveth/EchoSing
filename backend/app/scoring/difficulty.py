"""Difficulty levels: how far from the note (or the beat) still earns credit."""

from typing import NamedTuple

from app.domain.enums import Difficulty
from app.scoring.line_score import ScoringConfig
from app.scoring.rhythm import RhythmConfig


class Tolerance(NamedTuple):
    """Pitch error (semitones) with full credit, and from which there is none."""

    full_credit_semitones: float
    zero_credit_semitones: float


TOLERANCES: dict[Difficulty, Tolerance] = {
    Difficulty.EASY: Tolerance(1.0, 3.0),
    Difficulty.NORMAL: Tolerance(0.75, 2.5),
    Difficulty.HARD: Tolerance(0.5, 2.0),
}
"""Only the pitch tolerance changes: timing, hit threshold and the rest stay."""


def scoring_config(
    difficulty: Difficulty, base: ScoringConfig | None = None
) -> ScoringConfig:
    """Scoring parameters of a difficulty level.

    Args:
        difficulty: Level chosen by the player.
        base: Parameters to start from (defaults to ``ScoringConfig()``).

    Returns:
        ``base`` with the pitch tolerance of the level.
    """
    return (base or ScoringConfig()).model_copy(update=TOLERANCES[difficulty]._asdict())


class TimingTolerance(NamedTuple):
    """Onset offset (ms) with full credit, and from which there is none."""

    full_credit_ms: float
    zero_credit_ms: float


TIMING_TOLERANCES: dict[Difficulty, TimingTolerance] = {
    Difficulty.EASY: TimingTolerance(50.0, 130.0),
    Difficulty.NORMAL: TimingTolerance(40.0, 100.0),
    Difficulty.HARD: TimingTolerance(30.0, 75.0),
}
"""Rap mode: only the timing tolerance changes with the level.

Chosen on real rap (attacks ~180 ms apart) with simulated singers: normal
gives ~78 to a precise rapper (±20 ms), ~62 to one 50 ms late and ~33 to
random timing. Wider tolerances let random timing score close to good rapping,
since any attack is near some syllable.
"""


def rhythm_config(
    difficulty: Difficulty, base: RhythmConfig | None = None
) -> RhythmConfig:
    """Rhythm (rap mode) parameters of a difficulty level.

    Args:
        difficulty: Level chosen by the player.
        base: Parameters to start from (defaults to ``RhythmConfig()``).

    Returns:
        ``base`` with the timing tolerance of the level.
    """
    return (base or RhythmConfig()).model_copy(
        update=TIMING_TOLERANCES[difficulty]._asdict()
    )
