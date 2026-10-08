import time

import numpy as np
import pytest

from app.scoring.dtw import accumulate, band_mask, dtw


def naive_dtw(cost: np.ndarray) -> float:
    """Reference implementation: plain double loop (tests only)."""
    rows, columns = cost.shape
    total = np.full((rows + 1, columns + 1), np.inf)
    total[0, 0] = 0.0
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            total[i, j] = cost[i - 1, j - 1] + min(
                total[i - 1, j - 1], total[i - 1, j], total[i, j - 1]
            )
    return float(total[rows, columns])


def naive_optimal_cells(cost: np.ndarray) -> set[tuple[int, int]]:
    """Cells on any optimal path, by exhaustive forward/backward (tests only)."""
    rows, columns = cost.shape
    best = naive_dtw(cost)
    cells: set[tuple[int, int]] = set()
    for i in range(rows):
        for j in range(columns):
            before = naive_dtw(cost[: i + 1, : j + 1])
            after = naive_dtw(cost[i:, j:])
            if np.isclose(before + after - cost[i, j], best):
                cells.add((i, j))
    return cells


@pytest.mark.parametrize("seed", range(30))
def test_vectorized_cost_matches_the_naive_implementation(seed: int) -> None:
    rng = np.random.default_rng(seed)
    cost = rng.uniform(0, 6, size=(rng.integers(1, 25), rng.integers(1, 25)))

    assert dtw(cost).total_cost == pytest.approx(naive_dtw(cost))
    assert accumulate(cost)[-1, -1] == pytest.approx(naive_dtw(cost))


@pytest.mark.parametrize("seed", range(10))
def test_on_path_mask_matches_exhaustive_search(seed: int) -> None:
    rng = np.random.default_rng(100 + seed)
    # Integer costs create ties, i.e. several optimal paths.
    cost = rng.integers(0, 3, size=(rng.integers(1, 8), rng.integers(1, 8))).astype(
        float
    )

    result = dtw(cost)

    assert set(zip(*np.nonzero(result.on_path), strict=True)) == naive_optimal_cells(
        cost
    )


def test_identical_sequences_follow_the_diagonal() -> None:
    reference = np.array([60.0, 62.0, 64.0, 65.0])
    cost = np.abs(reference[:, None] - reference[None, :])

    result = dtw(cost)

    assert result.total_cost == 0.0
    np.testing.assert_array_equal(result.on_path, np.eye(4, dtype=bool))
    np.testing.assert_array_equal(result.row_costs, np.zeros(4))


def test_stretched_singing_is_aligned_at_no_cost() -> None:
    reference = np.array([60.0, 62.0, 64.0])
    sung = np.array([60.0, 60.0, 62.0, 62.0, 62.0, 64.0])  # same notes, slower
    cost = np.abs(reference[:, None] - sung[None, :])

    result = dtw(cost)

    assert result.total_cost == 0.0
    np.testing.assert_array_equal(result.row_costs, [0.0, 0.0, 0.0])


def test_completely_different_sequences() -> None:
    cost = np.full((3, 5), 6.0)

    result = dtw(cost)

    assert result.total_cost == pytest.approx(6.0 * 5)  # n + m - 1 cells
    np.testing.assert_array_equal(result.row_costs, [6.0, 6.0, 6.0])


@pytest.mark.parametrize("shape", [(1, 1), (1, 7), (7, 1)])
def test_single_frame_sequences(shape: tuple[int, int]) -> None:
    cost = np.arange(shape[0] * shape[1], dtype=float).reshape(shape)

    result = dtw(cost)

    assert result.total_cost == pytest.approx(cost.sum())
    assert result.on_path.all()


@pytest.mark.parametrize("shape", [(0, 5), (5, 0), (0, 0)])
def test_empty_sequences_are_rejected(shape: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        dtw(np.zeros(shape))


def test_every_reference_frame_gets_a_finite_cost() -> None:
    rng = np.random.default_rng(7)
    cost = rng.uniform(0, 6, size=(40, 90))

    result = dtw(cost, band_ratio=0.1)

    assert np.isfinite(result.row_costs).all()
    assert result.on_path.any(axis=1).all()


# --- Sakoe-Chiba band --------------------------------------------------------------


def test_band_restricts_cells_around_the_diagonal() -> None:
    mask = band_mask(11, 11, 0.2)

    assert mask[0, 0] and mask[10, 10] and mask[5, 7]
    assert not mask[0, 10] and not mask[10, 0] and not mask[2, 6]


@pytest.mark.parametrize(
    ("rows", "columns", "ratio"),
    [(2, 100, 0.0), (100, 2, 0.0), (1, 50, 0.0), (37, 53, 0.0), (5, 6, 0.05)],
)
def test_band_always_leaves_a_full_path(rows: int, columns: int, ratio: float) -> None:
    cost = np.ones((rows, columns))

    result = dtw(cost, band_ratio=ratio)

    assert np.isfinite(result.total_cost)
    assert np.isfinite(result.row_costs).all()


def test_band_prevents_absurd_alignments() -> None:
    # The reference melody appears only at the very end of the sung curve.
    reference = np.array([60.0, 62.0, 64.0, 65.0, 67.0])
    sung = np.concatenate((np.full(45, 50.0), reference))
    cost = np.minimum(np.abs(reference[:, None] - sung[None, :]), 6.0)

    free = dtw(cost)
    banded = dtw(cost, band_ratio=0.2)

    assert free.total_cost < banded.total_cost


@pytest.mark.parametrize("seed", range(10))
def test_banded_cost_matches_naive_on_the_masked_matrix(seed: int) -> None:
    rng = np.random.default_rng(200 + seed)
    rows, columns = int(rng.integers(2, 20)), int(rng.integers(2, 20))
    cost = rng.uniform(0, 6, size=(rows, columns))
    masked = np.where(band_mask(rows, columns, 0.3), cost, np.inf)

    assert dtw(cost, band_ratio=0.3).total_cost == pytest.approx(naive_dtw(masked))


# --- performance -------------------------------------------------------------------


def test_an_8_second_line_is_aligned_quickly() -> None:
    # Scoring compares curves every 20 ms: an 8 s line is 400 x 400 frames.
    rng = np.random.default_rng(1)
    cost = rng.uniform(0, 6, size=(400, 400))
    dtw(cost, band_ratio=0.25)  # warm-up

    started = time.perf_counter()
    dtw(cost, band_ratio=0.25)
    elapsed = time.perf_counter() - started

    # Real-time feedback budget (~16 ms measured on a desktop CPU).
    assert elapsed < 0.05
