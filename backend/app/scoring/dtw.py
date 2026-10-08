"""Dynamic Time Warping (DTW) on a precomputed cost matrix, vectorized.

DTW aligns two sequences monotonically, so a singer who starts a bit late or
holds a note longer is compared with the right part of the reference.

The accumulated cost is computed one anti-diagonal at a time: every cell of an
anti-diagonal depends only on the two previous anti-diagonals, so each one is
a single vectorized numpy operation. The loop runs over the ``n + m``
anti-diagonals (inherent to dynamic programming), never over cells.

Instead of backtracking cell by cell, a forward and a backward pass are
combined: a cell lies on an optimal path exactly when the cheapest path forced
through it costs the optimum, which gives a vectorized on-path mask.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True)
class DTWResult:
    """Outcome of aligning a reference (rows) with a sung curve (columns).

    Attributes:
        total_cost: Cost of the optimal alignment path.
        on_path: Mask ``(n, m)`` of the cells on an optimal path.
        row_costs: For each reference frame, the cheapest cost among the cells
            of an optimal path in its row (how well it was matched).
    """

    total_cost: float
    on_path: BoolArray
    row_costs: FloatArray


def accumulate(cost: FloatArray, step_penalty: float = 0.0) -> FloatArray:
    """Accumulated DTW cost with steps (1, 1), (1, 0) and (0, 1).

    Args:
        cost: Local cost matrix ``(n, m)``; ``inf`` marks forbidden cells.
        step_penalty: Extra cost of every horizontal or vertical step, so the
            path leaves the diagonal only when timing really differs.

    Returns:
        Matrix ``(n + 1, m + 1)`` where entry ``[i, j]`` is the cheapest path
        cost from cell ``(0, 0)`` to cell ``(i - 1, j - 1)``, both included;
        row and column 0 are a boundary of ``inf`` (except ``[0, 0] = 0``).
    """
    rows, columns = cost.shape
    diagonals = rows + columns - 1

    # Skewed layout: row k holds anti-diagonal i + j = k, at column i + 1
    # (column 0 is an inf pad standing for i = -1). Every dependency of a
    # diagonal is then a contiguous slice of the previous two rows.
    skew_cost = np.full((diagonals, rows + 1), np.inf)
    skew_cost[:, 1:] = _to_skewed(cost)

    # Only the finite cells of each diagonal need work (cells outside the
    # matrix or the band stay inf): find each diagonal's active range once.
    finite = np.isfinite(skew_cost[:, 1:])
    starts = finite.argmax(axis=1)
    ends = np.where(finite.any(axis=1), rows - finite[:, ::-1].argmax(axis=1), starts)

    skew_total = np.full((diagonals, rows + 1), np.inf)
    skew_total[0, 1] = cost[0, 0]
    no_diagonal = np.full(rows + 1, np.inf)
    best = np.empty(rows)
    for diagonal, start, end in zip(
        range(1, diagonals), starts[1:].tolist(), ends[1:].tolist(), strict=True
    ):
        previous = skew_total[diagonal - 1]
        before_previous = skew_total[diagonal - 2] if diagonal >= 2 else no_diagonal
        # For cell i (stored at column i + 1): up = (i - 1, j) and
        # left = (i, j - 1) are on the previous diagonal at columns i and
        # i + 1; (i - 1, j - 1) is on the one before at column i.
        active = best[: end - start]
        np.minimum(previous[start:end], previous[start + 1 : end + 1], out=active)
        if step_penalty:
            np.add(active, step_penalty, out=active)
        np.minimum(active, before_previous[start:end], out=active)
        np.add(
            skew_cost[diagonal, start + 1 : end + 1],
            active,
            out=skew_total[diagonal, start + 1 : end + 1],
        )

    total = np.full((rows + 1, columns + 1), np.inf)
    total[0, 0] = 0.0
    total[1:, 1:] = _from_skewed(skew_total[:, 1:], columns)
    return total


def _to_skewed(matrix: FloatArray) -> FloatArray:
    """Rearrange ``(n, m)`` so row ``k`` holds anti-diagonal ``i + j = k``.

    Returns an ``(n + m - 1, n)`` array with ``out[i + j, i] = matrix[i, j]``
    and ``inf`` elsewhere, built with a strided view instead of fancy indexing:
    in a flat buffer of rows of length ``n + m``, writing row ``i`` starting at
    column ``i`` is a view with a row stride one element longer than a row.
    """
    rows, columns = matrix.shape
    width = rows + columns
    flat = np.full(rows * width, np.inf)
    item = flat.itemsize
    shifted_rows = np.lib.stride_tricks.as_strided(
        flat, shape=(rows, columns), strides=((width + 1) * item, item)
    )
    shifted_rows[...] = matrix
    skewed: FloatArray = np.ascontiguousarray(
        flat.reshape(rows, width)[:, : width - 1].T
    )
    return skewed


def _from_skewed(skewed: FloatArray, columns: int) -> FloatArray:
    """Inverse of ``_to_skewed``: ``out[i, j] = skewed[i + j, i]``."""
    diagonals, rows = skewed.shape
    by_row = np.ascontiguousarray(skewed.T)  # by_row[i, k] = skewed[k, i]
    item = by_row.itemsize
    matrix: FloatArray = np.lib.stride_tricks.as_strided(
        by_row, shape=(rows, columns), strides=((diagonals + 1) * item, item)
    ).copy()
    return matrix


def band_mask(rows: int, columns: int, band_ratio: float) -> BoolArray:
    """Sakoe-Chiba band in normalized time, always containing a full path.

    A cell ``(i, j)`` is allowed when the relative positions ``i / (rows - 1)``
    and ``j / (columns - 1)`` differ by at most ``band_ratio``. The band is
    widened to at least one grid step, so a monotone path from the first to
    the last cell always exists, even for very different lengths.

    Args:
        rows: Reference frames.
        columns: Sung frames.
        band_ratio: Allowed deviation from the diagonal, as a fraction of the
            sequence duration.

    Returns:
        Boolean mask ``(rows, columns)``.
    """
    if min(rows, columns) == 1:
        return np.ones((rows, columns), dtype=np.bool_)
    step = max(1.0 / (rows - 1), 1.0 / (columns - 1))
    reference_position = np.arange(rows)[:, None] / (rows - 1)
    sung_position = np.arange(columns)[None, :] / (columns - 1)
    mask: BoolArray = (
        np.abs(reference_position - sung_position) <= max(band_ratio, step) + 1e-12
    )
    return mask


def dtw(
    cost: FloatArray, band_ratio: float | None = None, step_penalty: float = 0.0
) -> DTWResult:
    """Align a reference with a sung curve given their local cost matrix.

    Args:
        cost: Local cost ``(n, m)``: reference frames in rows, sung frames in
            columns. Must be finite and non-negative.
        band_ratio: Sakoe-Chiba band (see ``band_mask``), or None for none.
        step_penalty: Extra cost of every horizontal or vertical step.

    Returns:
        The optimal cost, the on-path mask and the per-reference-frame cost.

    Raises:
        ValueError: If either sequence is empty.
    """
    local = np.asarray(cost, dtype=np.float64)
    rows, columns = local.shape
    if rows == 0 or columns == 0:
        raise ValueError("DTW needs two non-empty sequences")
    if band_ratio is not None:
        local = np.where(band_mask(rows, columns, band_ratio), local, np.inf)

    # Step penalties sit on the edges between cells, so the cost of the best
    # path through a cell is still forward + backward - cell.
    forward = accumulate(local, step_penalty)[1:, 1:]
    backward = accumulate(local[::-1, ::-1], step_penalty)[1:, 1:][::-1, ::-1]
    total_cost = float(forward[-1, -1])

    with np.errstate(invalid="ignore"):  # inf - inf outside the band
        through = forward + backward - local
    on_path = np.isfinite(through) & np.isclose(
        through, total_cost, rtol=1e-9, atol=1e-9
    )
    row_costs: FloatArray = np.where(on_path, local, np.inf).min(axis=1)
    return DTWResult(total_cost=total_cost, on_path=on_path, row_costs=row_costs)
