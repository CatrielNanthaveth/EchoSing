from collections.abc import Sequence

import numpy as np
import pytest
from pydantic import ValidationError

from app.domain.enums import Difficulty
from app.schemas.analysis import LevelCurve
from app.scoring.difficulty import rhythm_config
from app.scoring.rhythm import RhythmConfig, analyze_rhythm, level_onsets

HOP = 10
PERIOD_MS = 200  # a syllable every 200 ms, as in rap
SYLLABLES = 12
FIRST_MS = 100
RNG = np.random.default_rng(5)


def attacks_at(
    times_ms: Sequence[float] | np.ndarray, length_ms: float, peak: float = -15.0
) -> np.ndarray:
    """A vocal level curve with a sharp attack at each time, decaying after it."""
    db = np.full(int(length_ms // HOP), -60.0)
    for time in times_ms:
        start = int(round(time / HOP))
        decay = peak - 2.0 * np.arange(12)  # -2 dB per frame over 120 ms
        end = min(start + decay.size, db.size)
        if 0 <= start < db.size:
            db[start:end] = np.maximum(db[start:end], decay[: end - start])
    return db


TIMES = [FIRST_MS + k * PERIOD_MS for k in range(SYLLABLES)]
LINE_MS = FIRST_MS + SYLLABLES * PERIOD_MS


def reference(times: Sequence[float] | None = None) -> LevelCurve:
    return LevelCurve(
        hop_ms=HOP, db=attacks_at(TIMES if times is None else times, LINE_MS).tolist()
    )


def sung(times: Sequence[float] | np.ndarray, peak: float = -25.0) -> np.ndarray:
    """The singer's level, with the 300 ms tail the client sends."""
    return attacks_at(times, LINE_MS + 300, peak)


# --- attack detection -----------------------------------------------------------------


def test_attacks_are_found_where_the_level_jumps() -> None:
    found = level_onsets(attacks_at([100, 300, 520], 800), HOP, RhythmConfig())

    np.testing.assert_allclose(found, [100, 300, 520])


def test_small_rises_are_not_attacks() -> None:
    db = np.full(50, -30.0)
    db[20:] = -26.0  # +4 dB: below the 6 dB rise

    assert level_onsets(db, HOP, RhythmConfig()).size == 0


def test_attacks_far_below_the_loudest_one_are_ignored() -> None:
    db = attacks_at([100], 600)
    db[40:44] = -50.0  # a breath 35 dB below the peak, rising from -60

    np.testing.assert_allclose(level_onsets(db, HOP, RhythmConfig()), [100])


def test_silence_has_no_attacks_however_it_fluctuates() -> None:
    noise = -75.0 + 10.0 * (np.arange(200, dtype=np.float64) % 2)  # all below -55

    assert level_onsets(noise, HOP, RhythmConfig()).size == 0


def test_attacks_too_close_together_count_once() -> None:
    found = level_onsets(attacks_at([100, 150], 500), HOP, RhythmConfig())

    np.testing.assert_allclose(found, [100])


def test_empty_curve() -> None:
    assert level_onsets(np.zeros(0), HOP, RhythmConfig()).size == 0


# --- scoring --------------------------------------------------------------------------


def test_perfect_timing_scores_100() -> None:
    analysis = analyze_rhythm(reference(), sung(TIMES), HOP)

    assert analysis.result.score == 100.0
    assert analysis.result.accuracy == 1.0
    assert analysis.result.hit
    assert analysis.result.voiced_frames == SYLLABLES  # weight: the attacks
    assert (analysis.missed, analysis.extra) == (0, 0)
    assert analysis.timing_offset_ms == 0.0
    assert analysis.reference_onsets_ms == analysis.sung_onsets_ms


@pytest.mark.parametrize(
    ("offset_ms", "expected"),
    [
        (30, 100.0),  # within full credit (40 ms)
        (70, 50.0),  # (100 - 70) / (100 - 40)
        (-70, 50.0),  # early
        (100, 0.0),  # beyond the reach
    ],
)
def test_timing_offsets_reduce_the_score(offset_ms: int, expected: float) -> None:
    analysis = analyze_rhythm(reference(), sung([t + offset_ms for t in TIMES]), HOP)

    assert analysis.result.score == pytest.approx(expected, abs=0.01)
    if expected > 0:
        assert analysis.timing_offset_ms == offset_ms


def test_missed_syllables_count_as_zero() -> None:
    analysis = analyze_rhythm(reference(), sung(TIMES[:6]), HOP)

    assert analysis.missed == 6
    assert analysis.result.score == pytest.approx(50.0, abs=0.01)


def test_extra_attacks_are_penalized() -> None:
    between = [t + PERIOD_MS / 2 for t in TIMES]

    analysis = analyze_rhythm(reference(), sung(sorted(TIMES + between)), HOP)

    assert analysis.extra == SYLLABLES
    assert analysis.result.score == pytest.approx(50.0, abs=0.01)


def test_silence_scores_0() -> None:
    analysis = analyze_rhythm(reference(), np.full(LINE_MS // HOP + 30, -90.0), HOP)

    assert analysis.result.score == 0.0
    assert analysis.missed == SYLLABLES
    assert analysis.timing_offset_ms is None


def test_random_timing_scores_low() -> None:
    analysis = analyze_rhythm(
        reference(), sung(RNG.uniform(0, LINE_MS, SYLLABLES)), HOP
    )

    assert analysis.result.score is not None and analysis.result.score < 40


def test_the_microphone_gain_does_not_matter() -> None:
    quiet = analyze_rhythm(reference(), sung(TIMES, peak=-45.0), HOP)

    assert quiet.result.score == 100.0


def test_latency_is_undone() -> None:
    late = sung([t + 120 for t in TIMES])  # arrives 120 ms late: all latency

    analysis = analyze_rhythm(reference(), late, HOP, latency_ms=120)

    assert analysis.result.score == 100.0


def test_negative_latency_pads_the_start() -> None:
    early = sung([t - 50 for t in TIMES])

    analysis = analyze_rhythm(reference(), early, HOP, latency_ms=-50)

    assert analysis.result.score == 100.0


def test_late_last_attack_past_the_line_end_still_matches() -> None:
    times = [*TIMES[:-1], LINE_MS - 20]  # the last attack right at the end
    late = sung([t + 50 for t in times])

    analysis = analyze_rhythm(reference(times), late, HOP)

    assert analysis.missed == 0


def test_attacks_after_the_line_do_not_count_as_extra() -> None:
    analysis = analyze_rhythm(reference(), sung([*TIMES, LINE_MS + 150]), HOP)

    assert analysis.extra == 0
    assert analysis.result.score == 100.0


def test_lines_with_too_few_attacks_are_not_scorable() -> None:
    analysis = analyze_rhythm(reference(TIMES[:2]), sung(TIMES[:2]), HOP)

    assert not analysis.result.scorable
    assert analysis.result.score is None
    assert analysis.pairs == []


def test_difficulty_sets_the_timing_tolerance() -> None:
    late = sung([t + 60 for t in TIMES])

    scores = [
        analyze_rhythm(reference(), late, HOP, config=rhythm_config(level)).result.score
        for level in (Difficulty.EASY, Difficulty.NORMAL, Difficulty.HARD)
    ]

    assert scores == [
        pytest.approx(87.5, abs=0.01),  # (130 - 60) / (130 - 50)
        pytest.approx(66.67, abs=0.01),  # (100 - 60) / (100 - 40)
        pytest.approx(33.33, abs=0.01),  # (75 - 60) / (75 - 30)
    ]


def test_difficulty_keeps_other_parameters() -> None:
    config = rhythm_config(Difficulty.EASY, RhythmConfig(min_onsets=5))

    assert (config.min_onsets, config.full_credit_ms) == (5, 50.0)


def test_invalid_credit_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RhythmConfig(full_credit_ms=200, zero_credit_ms=100)
