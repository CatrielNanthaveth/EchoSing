"""Versioned format of a song analysis: synced lyrics and reference pitch.

The analysis is produced by the ingestion pipeline, stored as JSONB in
``song_analyses.data`` and consumed by the catalog API and the scoring engine.
See ``docs/analysis-format.md`` for the full specification.
"""

import math
from typing import Any, Final, Literal, Self

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION: Final = 1
MIDI_MIN = 0.0
MIDI_MAX = 127.0


class UnsupportedFormatError(ValueError):
    """The stored analysis uses a format version this code cannot read."""


class _Frozen(BaseModel):
    """Immutable model that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Word(_Frozen):
    """A transcribed word with its timing.

    Attributes:
        text: The word as transcribed, including attached punctuation.
        start_ms: Start time from the beginning of the song.
        end_ms: End time (exclusive); greater than ``start_ms``.
        probability: Transcriber confidence in [0, 1], if available.
    """

    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int
    probability: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_times(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"Word {self.text!r} must end after it starts")
        return self


class LyricLine(_Frozen):
    """A line (verse) of lyrics, the unit that gets scored.

    Attributes:
        index: Zero-based position of the line in the song.
        start_ms: Start time of the line.
        end_ms: End time (exclusive) of the line.
        text: Full text of the line as displayed.
        words: Words of the line, in order and without overlaps.
    """

    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int
    text: str = Field(min_length=1)
    words: list[Word] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_words(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"Line {self.index} must end after it starts")
        for previous, current in zip(self.words, self.words[1:], strict=False):
            if current.start_ms < previous.end_ms:
                raise ValueError(f"Words of line {self.index} overlap or are unsorted")
        if (
            self.words[0].start_ms < self.start_ms
            or self.words[-1].end_ms > self.end_ms
        ):
            raise ValueError(f"Words of line {self.index} exceed the line bounds")
        return self


class PitchCurve(_Frozen):
    """Pitch track sampled every ``hop_ms``; frame ``i`` is centered at ``i * hop_ms``.

    Every frame keeps its pitch estimate and confidence, so the voicing decision
    (which frames count as singing) is made when reading, not when storing.

    Attributes:
        hop_ms: Time between consecutive frames.
        midi: Pitch per frame as fractional MIDI note number (69.0 = A4 =
            440 Hz), rounded to 0.01 (1 cent); None when there is no estimate.
        confidence: Voicing confidence per frame, as an integer in [0, 100].
    """

    hop_ms: int = Field(gt=0)
    midi: list[float | None]
    confidence: list[int]

    @model_validator(mode="after")
    def _check_frames(self) -> Self:
        if len(self.midi) != len(self.confidence):
            raise ValueError("midi and confidence must have the same length")
        pitch = np.array(self.midi, dtype=np.float64)
        voiced = pitch[~np.isnan(pitch)]
        if voiced.size and (voiced.min() < MIDI_MIN or voiced.max() > MIDI_MAX):
            raise ValueError(f"midi values must be within [{MIDI_MIN}, {MIDI_MAX}]")
        confidence = np.array(self.confidence, dtype=np.int64)
        if confidence.size and (confidence.min() < 0 or confidence.max() > 100):
            raise ValueError("confidence values must be within [0, 100]")
        return self

    @property
    def frame_count(self) -> int:
        """Number of frames in the curve."""
        return len(self.midi)

    def to_numpy(self, min_confidence: int = 0) -> NDArray[np.float64]:
        """Return the pitch as a float array, with NaN for unvoiced frames.

        Args:
            min_confidence: Frames below this confidence (0-100) become NaN.

        Returns:
            Fractional MIDI note numbers, one per frame.
        """
        pitch = np.array(self.midi, dtype=np.float64)
        pitch[np.array(self.confidence) < min_confidence] = np.nan
        return pitch

    def confidence_weights(self) -> NDArray[np.float64]:
        """Return the confidence of each frame scaled to [0, 1]."""
        return np.array(self.confidence, dtype=np.float64) / 100.0

    def slice_ms(self, start_ms: int, end_ms: int) -> "PitchCurve":
        """Return the frames whose time falls within ``[start_ms, end_ms)``.

        Bounds outside the curve are clipped; an empty or inverted range yields
        an empty curve.

        Args:
            start_ms: Start of the window.
            end_ms: End of the window (exclusive).

        Returns:
            A new curve with the same ``hop_ms``.
        """
        first = min(max(math.ceil(start_ms / self.hop_ms), 0), self.frame_count)
        last = min(max(math.ceil(end_ms / self.hop_ms), first), self.frame_count)
        return PitchCurve(
            hop_ms=self.hop_ms,
            midi=self.midi[first:last],
            confidence=self.confidence[first:last],
        )

    @classmethod
    def from_numpy(
        cls,
        midi: NDArray[np.floating[Any]],
        confidence: NDArray[np.floating[Any]],
        hop_ms: int,
    ) -> "PitchCurve":
        """Build a curve from pitch-extractor output.

        Args:
            midi: Fractional MIDI note per frame; NaN when there is no estimate.
            confidence: Voicing confidence per frame in [0, 1].
            hop_ms: Time between consecutive frames.

        Returns:
            A curve with pitch rounded to 0.01 and confidence quantized to 0-100.
        """
        rounded = np.round(np.asarray(midi, dtype=np.float64), 2)
        quantized = np.clip(np.round(np.asarray(confidence) * 100.0), 0, 100)
        # Object array so NaN can be replaced by None without a Python loop.
        pitch = rounded.astype(object)
        pitch[np.isnan(rounded)] = None
        return cls(
            hop_ms=hop_ms,
            midi=pitch.tolist(),
            confidence=quantized.astype(np.int64).tolist(),
        )


class PipelineInfo(_Frozen):
    """Models and parameters that produced the analysis, for reproducibility.

    Attributes:
        separator: Source separation model (e.g. ``htdemucs``).
        transcriber: Speech recognition model (e.g. ``whisper-large-v3-turbo``).
        pitch_extractor: Pitch model (e.g. ``torchcrepe-full``).
        language: Language detected or forced during transcription.
    """

    separator: str
    transcriber: str
    pitch_extractor: str
    language: str | None = None


class SongAnalysisData(_Frozen):
    """Complete analysis of a song, as stored in ``song_analyses.data``.

    Attributes:
        format_version: Version of this format.
        duration_ms: Duration of the song.
        pipeline: How the analysis was produced.
        lines: Lyric lines, ordered, non-overlapping, indexed ``0..n-1``.
        pitch: Reference pitch of the isolated vocals for the whole song.
    """

    format_version: Literal[1] = FORMAT_VERSION
    duration_ms: int = Field(gt=0)
    pipeline: PipelineInfo
    lines: list[LyricLine]
    pitch: PitchCurve

    @model_validator(mode="after")
    def _check_lines(self) -> Self:
        for position, line in enumerate(self.lines):
            if line.index != position:
                raise ValueError("Line indexes must be contiguous starting at 0")
        for previous, current in zip(self.lines, self.lines[1:], strict=False):
            if current.start_ms < previous.end_ms:
                raise ValueError(f"Line {current.index} overlaps the previous line")
        if self.lines and self.lines[-1].end_ms > self.duration_ms:
            raise ValueError("Lines must end within the song duration")
        return self

    def line_pitch(self, line_index: int) -> PitchCurve:
        """Return the reference pitch for one lyric line.

        Args:
            line_index: Index of the line.

        Returns:
            The slice of the song's pitch curve covering the line.

        Raises:
            IndexError: If the line does not exist.
        """
        if not 0 <= line_index < len(self.lines):
            raise IndexError(f"Line {line_index} does not exist")
        line = self.lines[line_index]
        return self.pitch.slice_ms(line.start_ms, line.end_ms)


def parse_analysis(format_version: int, data: dict[str, Any]) -> SongAnalysisData:
    """Validate an analysis loaded from the database.

    Args:
        format_version: Value of ``song_analyses.format_version``.
        data: Value of ``song_analyses.data``.

    Returns:
        The validated analysis.

    Raises:
        UnsupportedFormatError: If the format version is unknown.
        pydantic.ValidationError: If the data does not match the format.
    """
    if format_version != FORMAT_VERSION:
        raise UnsupportedFormatError(
            f"Unsupported analysis format version: {format_version}"
        )
    return SongAnalysisData.model_validate(data)
