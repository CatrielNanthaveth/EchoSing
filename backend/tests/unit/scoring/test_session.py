import pytest

from app.scoring.line_score import LineResult
from app.scoring.session import longest_run, summarize_session


def line(score: float, frames: int = 100, hit_threshold: float = 60) -> LineResult:
    return LineResult(
        scorable=True,
        score=score,
        accuracy=score / 100,
        hit=score >= hit_threshold,
        voiced_frames=frames,
    )


NOT_SCORABLE = LineResult(
    scorable=False, score=None, accuracy=None, hit=False, voiced_frames=3
)


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], 0),
        ([False, False], 0),
        ([True], 1),
        ([True, True, False, True], 2),
        ([False, True, True, True], 3),
        ([True, False, True, False, True], 1),
    ],
)
def test_longest_run(flags: list[bool], expected: int) -> None:
    assert longest_run(flags) == expected


def test_totals_weight_longer_lines_more() -> None:
    summary = summarize_session([line(100, frames=300), line(40, frames=100)])

    # (100 * 300 + 40 * 100) / 400
    assert summary.total_score == 85.0
    assert summary.accuracy == 0.85
    assert summary.scored_lines == 2
    assert summary.hit_lines == 1


def test_best_streak_counts_consecutive_hits() -> None:
    results = [line(90), line(80), line(20), line(70), line(75), line(95), line(10)]

    assert summarize_session(results).best_streak == 3


def test_lines_that_are_not_scorable_do_not_break_streaks() -> None:
    results = [line(90), NOT_SCORABLE, line(80), line(70)]

    summary = summarize_session(results)

    assert summary.best_streak == 3
    assert summary.scored_lines == 3
    assert summary.total_score == 80.0


def test_no_scorable_lines() -> None:
    summary = summarize_session([NOT_SCORABLE, NOT_SCORABLE])

    assert summary.total_score is None
    assert summary.accuracy is None
    assert (summary.best_streak, summary.scored_lines, summary.hit_lines) == (0, 0, 0)


def test_empty_performance() -> None:
    assert summarize_session([]).scored_lines == 0


def test_perfect_performance() -> None:
    summary = summarize_session([line(100), line(100), line(100)])

    assert (summary.total_score, summary.accuracy, summary.best_streak) == (
        100.0,
        1.0,
        3,
    )
