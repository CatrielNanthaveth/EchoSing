import numpy as np
import pytest

from app.scoring.analysis import analyze_line
from app.scoring.line_score import ScoringConfig, score_line
from tests.unit.scoring.test_line_score import HOP, MELODY, reference_curve, to_hz

SCORING_HOP = ScoringConfig().scoring_hop_ms
REFERENCE_FRAMES = int(MELODY.size * HOP / SCORING_HOP)
RNG = np.random.default_rng(3)


def late(frames: int, midi: np.ndarray = MELODY) -> np.ndarray:
    return np.concatenate((np.full(frames, np.nan), midi))


@pytest.mark.parametrize(
    ("sung", "latency_ms"),
    [
        (MELODY, 0.0),
        (MELODY - 1.0, 0.0),
        (MELODY + 0.4, 0.0),
        (late(15), 0.0),
        (late(12), 120.0),
        (RNG.uniform(45, 75, MELODY.size), 0.0),
        (np.full(MELODY.size, np.nan), 0.0),
        (np.zeros(0), 0.0),
    ],
)
def test_result_is_exactly_the_line_score(sung: np.ndarray, latency_ms: float) -> None:
    analysis = analyze_line(reference_curve(), to_hz(sung), HOP, latency_ms=latency_ms)

    assert analysis.result == score_line(
        reference_curve(), to_hz(sung), HOP, latency_ms=latency_ms
    )


def test_perfect_singing_matches_the_reference_everywhere() -> None:
    analysis = analyze_line(reference_curve(), to_hz(MELODY), HOP)

    assert analysis.hop_ms == SCORING_HOP
    assert len(analysis.reference_midi) == REFERENCE_FRAMES
    assert analysis.sung_midi == analysis.reference_midi
    assert analysis.aligned_midi == analysis.reference_midi
    assert analysis.credit == [1.0] * REFERENCE_FRAMES
    assert analysis.reference_weight == [0.95] * REFERENCE_FRAMES
    assert (analysis.timing_offset_ms, analysis.pitch_offset_semitones) == (0.0, 0.0)
    assert analysis.octave_shift == 0
    assert analysis.alignment_path[0] == (0, 0)
    assert analysis.alignment_path[-1] == (REFERENCE_FRAMES - 1, REFERENCE_FRAMES - 1)


def test_flat_singing_reports_the_pitch_offset() -> None:
    analysis = analyze_line(reference_curve(), to_hz(MELODY - 1.0), HOP)

    assert analysis.pitch_offset_semitones == -1.0
    assert analysis.timing_offset_ms == 0.0
    reference = np.array(analysis.reference_midi, dtype=float)
    aligned = np.array(analysis.aligned_midi, dtype=float)
    np.testing.assert_allclose(aligned, reference - 1.0)
    assert analysis.credit[0] == pytest.approx(2 / 3, abs=0.01)


def test_singing_an_octave_lower_is_shown_in_the_reference_register() -> None:
    analysis = analyze_line(reference_curve(), to_hz(MELODY - 12.0), HOP)

    assert analysis.octave_shift == -12
    assert analysis.sung_midi == analysis.reference_midi
    assert analysis.pitch_offset_semitones == 0.0
    assert analysis.result.score == 100.0


@pytest.mark.parametrize(("delay_ms", "expected"), [(150, 140.0), (-100, -100.0)])
def test_timing_offset_tells_late_and_early_entries(
    delay_ms: int, expected: float
) -> None:
    frames = abs(delay_ms) // HOP
    sung = late(frames) if delay_ms > 0 else MELODY[frames:]

    analysis = analyze_line(reference_curve(), to_hz(sung), HOP)

    assert analysis.timing_offset_ms == pytest.approx(expected, abs=SCORING_HOP)


def test_latency_is_undone_before_analyzing() -> None:
    analysis = analyze_line(reference_curve(), to_hz(late(12)), HOP, latency_ms=120)

    assert analysis.timing_offset_ms == 0.0
    assert analysis.sung_midi == analysis.reference_midi


def test_silence_has_no_alignment() -> None:
    analysis = analyze_line(reference_curve(), np.zeros(MELODY.size), HOP)

    assert analysis.result.score == 0.0
    assert analysis.credit == [0.0] * REFERENCE_FRAMES
    assert analysis.aligned_midi == [None] * REFERENCE_FRAMES
    assert analysis.sung_midi == [None] * REFERENCE_FRAMES
    assert analysis.alignment_path == []
    assert analysis.timing_offset_ms is None
    assert analysis.pitch_offset_semitones is None


def test_singing_only_outside_the_reach_of_the_reference_matches_nothing() -> None:
    # Voiced reference in the first 0.6 s only; singing starts at 1.6 s,
    # far beyond the 200 ms the alignment may drift.
    midi = np.where(np.arange(MELODY.size) < 60, MELODY, np.nan)
    confidence = np.where(np.isnan(midi), 0.05, 0.95)
    sung = np.where(np.arange(MELODY.size) >= 160, MELODY, np.nan)

    analysis = analyze_line(
        reference_curve(np.nan_to_num(midi, nan=57.0), confidence), to_hz(sung), HOP
    )

    assert analysis.result.score == 0.0
    assert analysis.alignment_path != []
    assert all(value is None for value in analysis.aligned_midi)
    assert analysis.timing_offset_ms is None


def test_unscorable_line_shows_the_curves_without_alignment() -> None:
    confidence = np.where(np.arange(MELODY.size) < 10, 0.95, 0.05)

    analysis = analyze_line(reference_curve(MELODY, confidence), to_hz(MELODY), HOP)

    assert not analysis.result.scorable
    assert analysis.result.voiced_frames == 5
    assert analysis.credit == [None] * REFERENCE_FRAMES
    assert analysis.alignment_path == []
    assert analysis.sung_midi[25] == 59.0  # what was sung is still shown


def test_pitch_offset_without_octave_invariance() -> None:
    config = ScoringConfig(octave_invariant=False)

    analysis = analyze_line(reference_curve(), to_hz(MELODY + 0.5), HOP, config=config)

    assert analysis.pitch_offset_semitones == 0.5
