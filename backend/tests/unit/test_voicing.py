import numpy as np
import pytest

from app.ml.transcription import TranscribedWord
from app.schemas.analysis import LyricLine, PitchCurve, Word
from app.services.voicing import (
    find_unvoiced_words,
    line_pitch_stats,
    midi_to_note_name,
    voiced_ratios,
)


def curve_from(confidence: list[int], midi: float = 60.0) -> PitchCurve:
    """Curve with 10 ms frames at a constant pitch."""
    return PitchCurve(hop_ms=10, midi=[midi] * len(confidence), confidence=confidence)


def word(text: str, start: int, end: int) -> TranscribedWord:
    return TranscribedWord(text=text, start_ms=start, end_ms=end)


@pytest.mark.parametrize(
    ("midi", "name"),
    [(69.0, "A4"), (60.0, "C4"), (47.4, "B2"), (48.6, "C#3"), (21.0, "A0")],
)
def test_midi_to_note_name(midi: float, name: str) -> None:
    assert midi_to_note_name(midi) == name


def test_voiced_ratios_per_span() -> None:
    # Frames 0-9 sung, 10-19 silent.
    curve = curve_from([90] * 10 + [0] * 10)

    ratios = voiced_ratios(
        [(0, 100), (100, 200), (50, 150), (300, 400), (40, 40)], curve, 50
    )

    np.testing.assert_allclose(ratios, [1.0, 0.0, 0.5, 0.0, 0.0])


def test_voiced_ratios_without_spans() -> None:
    assert voiced_ratios([], curve_from([90]), 50).size == 0


def test_hallucinated_phrase_over_silence_is_found() -> None:
    # Sung from 0 to 1 s, silence afterwards.
    curve = curve_from([90] * 100 + [0] * 100)
    words = [
        word("te", 0, 300),
        word("puedo", 300, 600),
        word("enamorar", 600, 1000),
        word("Gracias", 1000, 1200),
        word("por", 1200, 1300),
        word("ver", 1300, 1500),
        word("el", 1500, 1700),
        word("video.", 1700, 2000),
    ]

    found = find_unvoiced_words(words, curve, min_confidence=50, max_voiced_ratio=0.05)

    assert found == [3, 4, 5, 6, 7]


def test_isolated_unvoiced_words_are_kept() -> None:
    # Rap: short words landing on unvoiced frames between sung ones.
    confidence = ([90] * 30 + [0] * 10) * 5
    curve = curve_from(confidence)
    words = [word(f"w{i}", i * 200, (i + 1) * 200) for i in range(10)]

    found = find_unvoiced_words(words, curve, min_confidence=50, max_voiced_ratio=0.05)

    assert found == []


@pytest.mark.parametrize(("min_run", "expected"), [(2, [1, 2]), (3, [])])
def test_min_run_words(min_run: int, expected: list[int]) -> None:
    curve = curve_from([90] * 10 + [0] * 20 + [90] * 10)
    words = [
        word("a", 0, 100),
        word("b", 100, 200),
        word("c", 200, 300),
        word("d", 300, 400),
    ]

    found = find_unvoiced_words(
        words, curve, min_confidence=50, max_voiced_ratio=0.05, min_run_words=min_run
    )

    assert found == expected


def test_words_beyond_the_curve_count_as_unvoiced() -> None:
    curve = curve_from([90] * 10)
    words = [word("a", 5000, 5100), word("b", 5100, 5200), word("c", 5200, 5300)]

    assert find_unvoiced_words(
        words, curve, min_confidence=50, max_voiced_ratio=0.05
    ) == [
        0,
        1,
        2,
    ]


def test_no_words_no_findings() -> None:
    assert (
        find_unvoiced_words(
            [], curve_from([90]), min_confidence=50, max_voiced_ratio=0.05
        )
        == []
    )


def _line(index: int, text: str, start: int, end: int) -> LyricLine:
    return LyricLine(
        index=index,
        start_ms=start,
        end_ms=end,
        text=text,
        words=[Word(text=text, start_ms=start, end_ms=end)],
    )


def test_line_pitch_stats() -> None:
    midi = [57.0] * 50 + [60.0] * 50 + [64.0] * 100
    confidence = [90] * 100 + [0] * 100
    curve = PitchCurve(hop_ms=10, midi=midi, confidence=confidence)

    stats = line_pitch_stats(
        [_line(0, "sung", 0, 1000), _line(1, "silent", 1000, 2000)], curve, 50
    )

    assert stats[0].voiced_ratio == 1.0
    assert (stats[0].low_note, stats[0].high_note) == ("A3", "C4")
    assert stats[0].median_note in {"A#3", "B3"}
    assert stats[1].voiced_ratio == 0.0
    assert stats[1].median_note is None
    assert stats[1].low_note is None


def test_line_outside_the_curve_has_no_stats() -> None:
    stats = line_pitch_stats([_line(0, "late", 5000, 6000)], curve_from([90] * 10), 50)

    assert stats[0].voiced_ratio == 0.0
    assert stats[0].median_note is None
