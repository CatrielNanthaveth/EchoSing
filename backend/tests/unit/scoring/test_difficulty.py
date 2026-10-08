import numpy as np
import pytest

from app.domain.enums import Difficulty
from app.schemas.analysis import PitchCurve
from app.scoring.difficulty import scoring_config
from app.scoring.line_score import ScoringConfig, score_line

HOP = 10
MELODY = np.repeat([50.0, 52.0, 54.0, 55.0, 57.0, 55.0, 54.0, 52.0], 40)


def to_hz(midi: np.ndarray) -> np.ndarray:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def reference() -> PitchCurve:
    return PitchCurve(hop_ms=HOP, midi=MELODY.tolist(), confidence=[95] * MELODY.size)


@pytest.mark.parametrize(
    ("difficulty", "full", "zero"),
    [
        (Difficulty.EASY, 1.0, 3.0),
        (Difficulty.NORMAL, 0.75, 2.5),
        (Difficulty.HARD, 0.5, 2.0),
    ],
)
def test_levels_only_change_the_pitch_tolerance(
    difficulty: Difficulty, full: float, zero: float
) -> None:
    config = scoring_config(difficulty)

    assert (config.full_credit_semitones, config.zero_credit_semitones) == (full, zero)
    unchanged = {"full_credit_semitones", "zero_credit_semitones"}
    assert config.model_dump(exclude=unchanged) == ScoringConfig().model_dump(
        exclude=unchanged
    )


def test_hard_is_the_default_scoring() -> None:
    assert scoring_config(Difficulty.HARD) == ScoringConfig()


def test_levels_keep_other_base_parameters() -> None:
    base = ScoringConfig(hit_threshold=70)

    assert scoring_config(Difficulty.EASY, base).hit_threshold == 70


@pytest.mark.parametrize(
    ("difficulty", "expected"),
    [(Difficulty.EASY, 100.0), (Difficulty.NORMAL, 85.71), (Difficulty.HARD, 66.67)],
)
def test_one_semitone_off_by_level(difficulty: Difficulty, expected: float) -> None:
    result = score_line(
        reference(), to_hz(MELODY - 1.0), HOP, config=scoring_config(difficulty)
    )

    assert result.score == pytest.approx(expected, abs=0.01)
