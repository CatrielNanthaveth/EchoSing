import copy
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from app.schemas.analysis import (
    FORMAT_VERSION,
    PitchCurve,
    SongAnalysisData,
    UnsupportedFormatError,
    parse_analysis,
)


def _curve(
    midi: list[float | None], confidence: list[int], hop_ms: int = 10
) -> PitchCurve:
    return PitchCurve(hop_ms=hop_ms, midi=midi, confidence=confidence)


# --- fixture and versioning --------------------------------------------------


def test_fixture_is_valid(analysis_json: dict[str, Any]) -> None:
    analysis = parse_analysis(FORMAT_VERSION, analysis_json)

    assert analysis.format_version == 1
    assert [line.index for line in analysis.lines] == [0, 1, 2]
    assert analysis.pitch.frame_count == 300
    assert analysis.pipeline.language == "en"


def test_json_roundtrip_is_lossless(analysis_json: dict[str, Any]) -> None:
    analysis = parse_analysis(FORMAT_VERSION, analysis_json)

    assert analysis.model_dump(mode="json") == analysis_json


def test_unknown_format_version_is_rejected(analysis_json: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_analysis(2, analysis_json)


def test_data_with_mismatched_format_version_is_rejected(
    analysis_json: dict[str, Any],
) -> None:
    analysis_json["format_version"] = 2

    with pytest.raises(ValidationError):
        parse_analysis(FORMAT_VERSION, analysis_json)


def test_unknown_fields_are_rejected(analysis_json: dict[str, Any]) -> None:
    analysis_json["lines"][0]["color"] = "red"

    with pytest.raises(ValidationError):
        parse_analysis(FORMAT_VERSION, analysis_json)


# --- lyric invariants --------------------------------------------------------


def _broken(analysis_json: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    """Return a copy of the fixture with one nested value replaced."""
    data = copy.deepcopy(analysis_json)
    target: Any = data
    *parents, last = path.split(".")
    for key in parents:
        target = target[int(key)] if key.isdigit() else target[key]
    target[int(last) if last.isdigit() else last] = value
    return data


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("lines.0.words.0.end_ms", 200),  # word ends when it starts
        ("lines.0.words.1.start_ms", 400),  # words overlap
        ("lines.0.words.0.start_ms", 150),  # word starts before its line
        ("lines.0.end_ms", 800),  # last word ends after its line
        ("lines.0.end_ms", 200),  # line ends when it starts
        ("lines.0.words", []),  # line without words
        ("lines.0.text", ""),  # empty line text
        ("lines.1.index", 5),  # non-contiguous indexes
        ("lines.1.start_ms", 850),  # lines overlap
        ("lines.2.end_ms", 3500),  # line beyond the song duration
        ("lines.0.words.0.probability", 1.5),  # probability out of range
        ("duration_ms", 0),  # empty song
    ],
)
def test_invalid_lyrics_are_rejected(
    analysis_json: dict[str, Any], path: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        SongAnalysisData.model_validate(_broken(analysis_json, path, value))


def test_song_without_lines_is_valid(analysis_json: dict[str, Any]) -> None:
    analysis_json["lines"] = []

    assert SongAnalysisData.model_validate(analysis_json).lines == []


# --- pitch curve -------------------------------------------------------------


@pytest.mark.parametrize(
    ("midi", "confidence", "hop_ms"),
    [
        ([60.0, 61.0], [90], 10),  # length mismatch
        ([128.5], [90], 10),  # above MIDI range
        ([-1.0], [90], 10),  # below MIDI range
        ([60.0], [101], 10),  # confidence above 100
        ([60.0], [-1], 10),  # negative confidence
        ([60.0], [90], 0),  # non-positive hop
    ],
)
def test_invalid_pitch_curves_are_rejected(
    midi: list[float | None], confidence: list[int], hop_ms: int
) -> None:
    with pytest.raises(ValidationError):
        _curve(midi, confidence, hop_ms)


def test_empty_and_all_null_curves_are_valid() -> None:
    assert _curve([], []).frame_count == 0
    assert np.isnan(_curve([None, None], [0, 0]).to_numpy()).all()


def test_to_numpy_masks_frames_below_min_confidence() -> None:
    curve = _curve([None, 57.02, 57.05, 59.98], [3, 41, 88, 95])

    np.testing.assert_array_equal(
        curve.to_numpy(), np.array([np.nan, 57.02, 57.05, 59.98])
    )
    np.testing.assert_array_equal(
        curve.to_numpy(min_confidence=50), np.array([np.nan, np.nan, 57.05, 59.98])
    )


def test_confidence_weights_are_scaled_to_unit_range() -> None:
    curve = _curve([60.0, 60.0, 60.0], [0, 50, 100])

    np.testing.assert_allclose(curve.confidence_weights(), [0.0, 0.5, 1.0])


def test_from_numpy_rounds_and_quantizes() -> None:
    curve = PitchCurve.from_numpy(
        midi=np.array([np.nan, 57.0249, 57.0251, 69.0]),
        confidence=np.array([0.004, 0.416, 0.995, 1.2]),
        hop_ms=10,
    )

    assert curve.midi == [None, 57.02, 57.03, 69.0]
    assert curve.confidence == [0, 42, 100, 100]


def test_from_numpy_to_numpy_roundtrip_within_one_cent() -> None:
    rng = np.random.default_rng(seed=7)
    midi = rng.uniform(40.0, 80.0, 1000)
    midi[::10] = np.nan

    restored = PitchCurve.from_numpy(midi, np.ones(1000), 10).to_numpy()

    np.testing.assert_array_equal(np.isnan(restored), np.isnan(midi))
    voiced = ~np.isnan(midi)
    assert np.max(np.abs(restored[voiced] - midi[voiced])) <= 0.005 + 1e-9


# --- slicing -----------------------------------------------------------------


@pytest.fixture
def ten_frames() -> PitchCurve:
    # Frame i is at i * 10 ms and has pitch 60 + i.
    return _curve([60.0 + i for i in range(10)], list(range(10)))


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "expected_frames"),
    [
        (0, 100, list(range(10))),  # whole curve
        (20, 50, [2, 3, 4]),  # aligned window, end exclusive
        (15, 51, [2, 3, 4, 5]),  # unaligned bounds round inwards to frame times
        (-50, 25, [0, 1, 2]),  # start clipped
        (75, 500, [8, 9]),  # end clipped
        (40, 40, []),  # empty window
        (60, 20, []),  # inverted window
        (200, 300, []),  # beyond the curve
    ],
)
def test_slice_ms(
    ten_frames: PitchCurve, start_ms: int, end_ms: int, expected_frames: list[int]
) -> None:
    sliced = ten_frames.slice_ms(start_ms, end_ms)

    assert sliced.hop_ms == 10
    assert sliced.midi == [60.0 + i for i in expected_frames]
    assert sliced.confidence == expected_frames


def test_line_pitch_covers_the_line(analysis_json: dict[str, Any]) -> None:
    analysis = parse_analysis(FORMAT_VERSION, analysis_json)

    line_pitch = analysis.line_pitch(1)  # 1000-1800 ms -> frames 100..179

    assert line_pitch.frame_count == 80
    assert line_pitch.midi == analysis.pitch.midi[100:180]
    # Sung frames are confidently voiced and close to the notes of the line.
    voiced = line_pitch.to_numpy(min_confidence=50)
    assert not np.isnan(voiced).any()
    assert np.all((voiced > 59.5) & (voiced < 62.5))


@pytest.mark.parametrize("line_index", [-1, 3])
def test_line_pitch_rejects_missing_lines(
    analysis_json: dict[str, Any], line_index: int
) -> None:
    analysis = parse_analysis(FORMAT_VERSION, analysis_json)

    with pytest.raises(IndexError):
        analysis.line_pitch(line_index)


def test_models_are_immutable(analysis_json: dict[str, Any]) -> None:
    analysis = parse_analysis(FORMAT_VERSION, analysis_json)

    with pytest.raises(ValidationError):
        analysis.duration_ms = 1  # type: ignore[misc]
