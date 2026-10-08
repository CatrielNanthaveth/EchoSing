import numpy as np
import pytest
from pydantic import ValidationError

from app.schemas.analysis import PitchCurve
from app.scoring.line_score import ScoringConfig, score_line

HOP = 10
# A 2.4 s phrase: six notes of 400 ms (A3 B3 C#4 D4 C#4 B3), fully voiced.
NOTES = [57.0, 59.0, 61.0, 62.0, 61.0, 59.0]
MELODY = np.repeat(NOTES, 40)


def reference_curve(
    midi: np.ndarray = MELODY, confidence: np.ndarray | None = None
) -> PitchCurve:
    conf = np.full(midi.size, 0.95) if confidence is None else confidence
    return PitchCurve.from_numpy(midi, conf, HOP)


def to_hz(midi: np.ndarray) -> np.ndarray:
    hz = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    return np.where(np.isnan(midi), 0.0, hz)


# --- perfect and near-perfect singing ----------------------------------------------


def test_exact_singing_scores_100() -> None:
    result = score_line(reference_curve(), to_hz(MELODY), HOP)

    assert result.scorable is True
    assert result.score == 100.0
    assert result.accuracy == 1.0
    assert result.hit is True
    assert result.voiced_frames == 120  # 2.4 s at 20 ms


@pytest.mark.parametrize("octaves", [-1, 1])
def test_singing_an_octave_away_scores_100(octaves: int) -> None:
    result = score_line(reference_curve(), to_hz(MELODY + 12 * octaves), HOP)

    assert result.score == 100.0


def test_octave_counts_as_wrong_without_octave_invariance() -> None:
    config = ScoringConfig(octave_invariant=False)

    result = score_line(reference_curve(), to_hz(MELODY + 12), HOP, config=config)

    assert result.score == 0.0
    assert result.hit is False


@pytest.mark.parametrize(
    ("offset", "expected_score"),
    [
        (0.25, 100.0),  # within a quarter tone: full credit
        (0.5, 100.0),  # boundary: full credit
        (1.0, 66.67),  # linear decay: (2 - 1) / (2 - 0.5)
        (1.5, 33.33),
    ],
)
def test_detuned_singing_gets_partial_credit(
    offset: float, expected_score: float
) -> None:
    result = score_line(reference_curve(), to_hz(MELODY + offset), HOP)

    assert result.score == pytest.approx(expected_score, abs=0.01)
    assert result.accuracy == (1.0 if offset <= 0.5 else 0.0)


@pytest.mark.parametrize("offset", [2.0, 3.0])
def test_far_detuned_singing_gets_nothing(offset: float) -> None:
    # This melody moves by 2- and 3-semitone steps, so the detuned voice
    # matches neighboring notes: the step penalty keeps DTW from using them.
    result = score_line(reference_curve(), to_hz(MELODY + offset), HOP)

    assert result.score == 0.0
    assert result.hit is False


# --- rhythm and timing (why DTW) -----------------------------------------------------


def test_rhythm_variations_are_barely_penalized() -> None:
    # Same notes, but each change happens up to 100 ms early or late.
    lengths = np.array([40, 48, 32, 45, 35, 40])

    result = score_line(reference_curve(), to_hz(np.repeat(NOTES, lengths)), HOP)

    assert result.score is not None and result.score > 95


def test_off_key_singing_cannot_borrow_neighboring_notes() -> None:
    # The flat melody matches other reference notes in pitch; without the warp
    # limit and step penalty DTW would align to them and over-reward it.
    unconstrained = ScoringConfig(max_warp_ms=None, step_penalty_semitones=0)

    fair = score_line(reference_curve(), to_hz(MELODY + 1.0), HOP)
    lenient = score_line(
        reference_curve(), to_hz(MELODY + 1.0), HOP, config=unconstrained
    )

    assert fair.score == pytest.approx(66.67, abs=0.01)
    assert lenient.score is not None and lenient.score > 66.67 + 2


def test_entering_150_ms_late_is_barely_penalized() -> None:
    late = np.concatenate((np.full(15, np.nan), MELODY))

    result = score_line(reference_curve(), to_hz(late), HOP)

    assert result.score is not None and result.score > 90


def test_measured_latency_is_compensated() -> None:
    late = np.concatenate((np.full(15, np.nan), MELODY))

    result = score_line(reference_curve(), to_hz(late), HOP, latency_ms=150)

    assert result.score == 100.0


def test_browser_frame_rate_is_resampled() -> None:
    browser_hop = 512 / 44.1  # ~11.6 ms
    times = np.arange(int(MELODY.size * HOP / browser_hop)) * browser_hop
    sung = MELODY[np.minimum((times / HOP).astype(int), MELODY.size - 1)]

    result = score_line(reference_curve(), to_hz(sung), browser_hop)

    assert result.score is not None and result.score > 97


# --- bad or missing singing ----------------------------------------------------------


def test_random_singing_scores_low() -> None:
    rng = np.random.default_rng(3)
    noise = rng.uniform(45, 75, size=MELODY.size)

    result = score_line(reference_curve(), to_hz(noise), HOP)

    # Chance level: random notes fall near the right one now and then.
    assert result.score is not None and result.score < 40
    assert result.hit is False


@pytest.mark.parametrize("sung", [np.zeros(240), np.array([]), np.full(240, np.nan)])
def test_silence_scores_0(sung: np.ndarray) -> None:
    result = score_line(reference_curve(), sung, HOP)

    assert result.scorable is True
    assert result.score == 0.0
    assert result.accuracy == 0.0


def test_partially_sung_line() -> None:
    half = MELODY.copy()
    half[120:] = np.nan  # stops singing halfway

    result = score_line(reference_curve(), to_hz(half), HOP)

    assert result.score is not None and 40 < result.score < 60


# --- what gets scored ----------------------------------------------------------------


def test_line_with_too_little_singing_is_not_scorable() -> None:
    confidence = np.zeros(MELODY.size)
    confidence[:15] = 0.95  # 150 ms of singing < 200 ms

    result = score_line(reference_curve(confidence=confidence), to_hz(MELODY), HOP)

    assert result.scorable is False
    assert (result.score, result.accuracy, result.hit) == (None, None, False)
    assert result.voiced_frames < 10


def test_silent_reference_is_not_scorable() -> None:
    result = score_line(
        reference_curve(confidence=np.zeros(MELODY.size)), to_hz(MELODY), HOP
    )

    assert result.scorable is False
    assert result.voiced_frames == 0


def test_unvoiced_reference_frames_are_ignored() -> None:
    confidence = np.full(MELODY.size, 0.95)
    confidence[100:140] = 0.1  # a breath in the reference
    sung = MELODY.copy()
    sung[100:140] = 30.0  # whatever the singer does there does not count

    result = score_line(reference_curve(confidence=confidence), to_hz(sung), HOP)

    assert result.score is not None and result.score > 95


def test_confident_frames_weigh_more() -> None:
    confidence = np.full(MELODY.size, 1.0)
    confidence[120:] = 0.55  # second half: barely above the threshold
    sung = MELODY.copy()
    sung[120:] += 3.0  # second half off-key

    result = score_line(reference_curve(confidence=confidence), to_hz(sung), HOP)

    # Unweighted it would be 50; the confident, well-sung half dominates.
    assert result.score is not None and result.score > 60


def test_zero_weights_fall_back_to_uniform() -> None:
    config = ScoringConfig(min_reference_confidence=0)
    reference = reference_curve(confidence=np.zeros(MELODY.size))

    result = score_line(reference, to_hz(MELODY), HOP, config=config)

    assert result.scorable is True
    assert result.score == 100.0


def test_hit_threshold_is_configurable() -> None:
    sung = to_hz(MELODY + 1.0)  # ~66.67

    assert score_line(reference_curve(), sung, HOP).hit is True
    strict = ScoringConfig(hit_threshold=70)
    assert score_line(reference_curve(), sung, HOP, config=strict).hit is False


def test_without_warp_limit() -> None:
    result = score_line(
        reference_curve(), to_hz(MELODY), HOP, config=ScoringConfig(max_warp_ms=None)
    )

    assert result.score == 100.0


def test_invalid_credit_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(full_credit_semitones=2.0, zero_credit_semitones=1.0)


def test_singing_past_the_line_end_is_ignored() -> None:
    rng = np.random.default_rng(9)
    tail = rng.uniform(40, 80, size=30)  # 300 ms of noise after the line

    result = score_line(reference_curve(), to_hz(np.concatenate((MELODY, tail))), HOP)

    assert result.score == 100.0


# Rap-like line: short sung bursts separated by pauses (50% unvoiced).
PAUSED_MIDI = np.repeat([50.0, 51.0, 49.0, 52.0, 50.0, 48.0, 51.0, 50.0], 30)
PAUSED_CONFIDENCE = np.tile(np.r_[np.full(30, 0.95), np.full(30, 0.05)], 4)
PAUSED_SUNG = np.where(PAUSED_CONFIDENCE >= 0.5, PAUSED_MIDI, np.nan)


def test_lines_with_many_pauses_keep_their_timing() -> None:
    # Comparing only the voiced reference frames against the full sung curve
    # compressed the reference in time and broke the alignment.
    reference = reference_curve(PAUSED_MIDI, PAUSED_CONFIDENCE)

    result = score_line(reference, to_hz(PAUSED_SUNG), HOP)

    assert result.score == 100.0
    assert result.accuracy == 1.0


def test_detuned_singing_with_pauses_gets_partial_credit() -> None:
    reference = reference_curve(PAUSED_MIDI, PAUSED_CONFIDENCE)

    result = score_line(reference, to_hz(PAUSED_SUNG - 1.0), HOP)

    assert result.score == pytest.approx(66.67, abs=0.01)


@pytest.mark.parametrize("shift_frames", [-15, 15])
def test_shifted_singing_with_pauses_is_barely_penalized(shift_frames: int) -> None:
    reference = reference_curve(PAUSED_MIDI, PAUSED_CONFIDENCE)
    shifted = np.roll(PAUSED_SUNG, shift_frames)  # 150 ms early or late

    result = score_line(reference, to_hz(shifted), HOP)

    assert result.score is not None and result.score > 90


def test_choppy_detection_inside_notes_is_bridged() -> None:
    # Real-time detection often drops 40-80 ms inside sung notes.
    choppy = MELODY.copy()
    choppy[np.arange(MELODY.size) % 12 >= 7] = np.nan  # 50 ms holes every 120 ms

    bridged = score_line(reference_curve(), to_hz(choppy), HOP)
    raw = score_line(
        reference_curve(), to_hz(choppy), HOP, config=ScoringConfig(max_gap_ms=0)
    )

    assert bridged.score is not None and bridged.score > 95
    assert raw.score is not None and raw.score < bridged.score - 10


def test_real_pauses_are_not_bridged() -> None:
    # Singing only the first and last notes leaves a 1.6 s pause: not a gap.
    sung = np.where(
        (np.arange(MELODY.size) < 40) | (np.arange(MELODY.size) >= 200), MELODY, np.nan
    )

    result = score_line(reference_curve(), to_hz(sung), HOP)

    assert result.score is not None and result.score < 40
