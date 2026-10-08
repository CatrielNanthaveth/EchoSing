import numpy as np
import pytest

from app.scoring.pitch import (
    compensate_latency,
    hz_to_midi,
    resample,
    semitone_error,
)

NAN = np.nan


# --- hz_to_midi ------------------------------------------------------------------


def test_hz_to_midi_known_values() -> None:
    np.testing.assert_allclose(
        hz_to_midi(np.array([440.0, 880.0, 220.0, 261.6256])),
        [69.0, 81.0, 57.0, 60.0],
        atol=1e-4,
    )


def test_hz_to_midi_invalid_values_are_unvoiced() -> None:
    midi = hz_to_midi(np.array([0.0, -1.0, NAN, np.inf, 440.0]))

    assert np.isnan(midi[:4]).all()
    assert midi[4] == 69.0


# --- resample --------------------------------------------------------------------


def test_resample_to_the_same_rate_is_identity() -> None:
    values = np.array([60.0, 61.0, NAN, 62.0])

    np.testing.assert_array_equal(resample(values, 10, 10), values)


def test_upsampling_interpolates_linearly() -> None:
    np.testing.assert_allclose(
        resample(np.array([60.0, 62.0, 64.0]), 10, 5), [60, 61, 62, 63, 64]
    )


def test_downsampling_keeps_the_time_span() -> None:
    values = np.arange(11, dtype=np.float64) + 60  # 0..100 ms every 10 ms

    result = resample(values, 10, 25)  # 0, 25, 50, 75, 100 ms

    np.testing.assert_allclose(result, [60.0, 62.5, 65.0, 67.5, 70.0])


def test_non_integer_ratio_like_a_browser_hop() -> None:
    # 512 samples at 44.1 kHz ~ 11.61 ms per frame.
    values = np.full(100, 57.0)

    result = resample(values, 512 / 44.1, 10)

    assert result.size == int(99 * 512 / 44.1 / 10) + 1
    np.testing.assert_allclose(result, 57.0)


def test_silences_are_not_bridged() -> None:
    values = np.array([60.0, NAN, 64.0, 64.0])

    result = resample(values, 10, 5)  # 0, 5, 10, 15, 20, 25, 30 ms

    assert result[0] == 60.0
    assert np.isnan(result[1:4]).all()  # touching the unvoiced frame
    np.testing.assert_allclose(result[4:], [64.0, 64.0, 64.0])


def test_resample_empty_curve() -> None:
    assert resample(np.array([]), 10, 5).size == 0


def test_resample_single_frame() -> None:
    np.testing.assert_array_equal(resample(np.array([60.0]), 10, 5), [60.0])


@pytest.mark.parametrize(("source", "target"), [(0, 10), (10, 0), (-1, 10)])
def test_resample_rejects_invalid_hops(source: float, target: float) -> None:
    with pytest.raises(ValueError):
        resample(np.array([60.0]), source, target)


# --- compensate_latency ----------------------------------------------------------


def test_positive_latency_drops_the_late_frames() -> None:
    values = np.array([NAN, NAN, 60.0, 61.0])

    np.testing.assert_array_equal(compensate_latency(values, 20, 10), [60.0, 61.0])


def test_latency_is_rounded_to_whole_frames() -> None:
    values = np.array([1.0, 2.0, 3.0])

    np.testing.assert_array_equal(compensate_latency(values, 14, 10), [2.0, 3.0])
    np.testing.assert_array_equal(compensate_latency(values, 4, 10), [1.0, 2.0, 3.0])


def test_negative_latency_pads_with_silence() -> None:
    result = compensate_latency(np.array([60.0]), -20, 10)

    assert np.isnan(result[:2]).all()
    assert result[2] == 60.0


def test_latency_longer_than_the_curve_empties_it() -> None:
    assert compensate_latency(np.array([60.0, 61.0]), 500, 10).size == 0


def test_compensate_latency_does_not_modify_the_input() -> None:
    values = np.array([60.0, 61.0])
    result = compensate_latency(values, 0, 10)
    result[0] = 0.0

    assert values[0] == 60.0


def test_compensate_latency_rejects_invalid_hop() -> None:
    with pytest.raises(ValueError):
        compensate_latency(np.array([60.0]), 10, 0)


# --- semitone_error --------------------------------------------------------------


@pytest.mark.parametrize(
    ("sung", "reference", "expected"),
    [
        (60.0, 60.0, 0.0),
        (60.5, 60.0, 0.5),
        (59.0, 60.0, 1.0),
        (72.0, 60.0, 0.0),  # octave above
        (48.0, 60.0, 0.0),  # octave below
        (73.0, 60.0, 1.0),  # octave + semitone
        (66.0, 60.0, 6.0),  # tritone: maximum folded error
        (65.0, 60.0, 5.0),
        (67.0, 60.0, 5.0),  # a fifth is closer from the octave above
    ],
)
def test_octave_invariant_error(sung: float, reference: float, expected: float) -> None:
    assert semitone_error(np.array(sung), np.array(reference)) == pytest.approx(
        expected
    )


def test_plain_error_without_octave_invariance() -> None:
    error = semitone_error(np.array([72.0]), np.array([60.0]), octave_invariant=False)

    assert error[0] == 12.0


def test_nan_propagates() -> None:
    assert np.isnan(semitone_error(np.array([NAN]), np.array([60.0]))).all()


def test_broadcasting_builds_a_cost_matrix() -> None:
    reference = np.array([60.0, 62.0])
    sung = np.array([60.0, 61.0, 62.0])

    matrix = semitone_error(sung[None, :], reference[:, None])

    np.testing.assert_allclose(matrix, [[0, 1, 2], [2, 1, 0]])
