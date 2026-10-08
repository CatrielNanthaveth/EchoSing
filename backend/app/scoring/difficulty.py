"""Difficulty levels: how far from the note singing still earns credit."""

from typing import NamedTuple

from app.domain.enums import Difficulty
from app.scoring.line_score import ScoringConfig


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
