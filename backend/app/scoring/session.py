"""Aggregate line results into the score of a whole performance."""

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel

from app.scoring.line_score import LineResult


class SessionSummary(BaseModel):
    """Totals of a performance.

    Attributes:
        total_score: Line scores averaged by sung reference length, 0-100;
            None when no line was scorable.
        accuracy: Fraction of in-tune reference frames over all scorable
            lines, 0-1; None when no line was scorable.
        best_streak: Longest run of consecutive hit lines. Lines that are not
            scorable neither count nor break a streak.
        scored_lines: Number of scorable lines.
        hit_lines: Number of hit lines.
    """

    total_score: float | None
    accuracy: float | None
    best_streak: int
    scored_lines: int
    hit_lines: int


def longest_run(flags: Sequence[bool]) -> int:
    """Length of the longest run of consecutive True values.

    Args:
        flags: Values in order.

    Returns:
        The longest run (0 if there is none).
    """
    if not flags:
        return 0
    padded = np.concatenate(([0], np.asarray(flags, dtype=np.int8), [0]))
    edges = np.diff(padded)
    lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
    return int(lengths.max()) if lengths.size else 0


def summarize_session(lines: Sequence[LineResult]) -> SessionSummary:
    """Aggregate the results of a performance, given in line order.

    Longer lines weigh more than short ones (an "ooh" counts less than a
    verse), using the number of sung reference frames as weight.

    Args:
        lines: Results of the sung lines, ordered by line index.

    Returns:
        The performance totals.
    """
    scorable = [
        line
        for line in lines
        if line.scorable and line.score is not None and line.accuracy is not None
    ]
    hits = [line.hit for line in scorable]
    if not scorable:
        return SessionSummary(
            total_score=None,
            accuracy=None,
            best_streak=0,
            scored_lines=0,
            hit_lines=0,
        )

    weights = np.array([line.voiced_frames for line in scorable], dtype=np.float64)
    scores = np.array([line.score for line in scorable], dtype=np.float64)
    accuracies = np.array([line.accuracy for line in scorable], dtype=np.float64)
    return SessionSummary(
        total_score=round(float(np.average(scores, weights=weights)), 2),
        accuracy=round(float(np.average(accuracies, weights=weights)), 4),
        best_streak=longest_run(hits),
        scored_lines=len(scorable),
        hit_lines=sum(hits),
    )
