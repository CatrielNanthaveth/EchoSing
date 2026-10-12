"""Scoring of a sung line in the session's mode: melody (pitch) or rap (rhythm)."""

from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import TypeAdapter

from app.db.repositories.songs import AnalysisReference
from app.domain.enums import Difficulty, ScoringMode
from app.schemas.analysis import LevelCurve, LyricLine, PitchCurve
from app.schemas.practice import LineScoring
from app.schemas.sessions import SungPitch
from app.scoring.analysis import analyze_line
from app.scoring.difficulty import rhythm_config, scoring_config
from app.scoring.line_score import LineResult, ScoringConfig, score_line
from app.scoring.rhythm import (
    SILENT_DB,
    RhythmAnalysis,
    RhythmConfig,
    analyze_rhythm,
)

_LINES = TypeAdapter(list[LyricLine])


class RhythmUnavailableError(Exception):
    """The song's analysis has no vocals' level curve, which rap mode needs."""


class MissingLevelError(Exception):
    """Rap mode needs the microphone level (``level_db``) of the sung line."""


@dataclass(frozen=True)
class SongReference:
    """The reference curves and lines of one analysis.

    Attributes:
        lines: Lyric lines.
        pitch: Reference pitch of the whole song.
        level: Loudness of the reference vocals; None in older analyses.
    """

    lines: list[LyricLine]
    pitch: PitchCurve
    level: LevelCurve | None

    @classmethod
    def from_raw(cls, raw: AnalysisReference) -> "SongReference":
        """Validate the raw JSON values read from the analysis."""
        level: dict[str, Any] | None = raw.level
        return cls(
            lines=_LINES.validate_python(raw.lines),
            pitch=PitchCurve.model_validate(raw.pitch),
            level=None if level is None else LevelCurve.model_validate(level),
        )

    def line_pitch(self, line: LyricLine) -> PitchCurve:
        """Reference pitch of a line."""
        return self.pitch.slice_ms(line.start_ms, line.end_ms)

    def line_level(self, line: LyricLine) -> LevelCurve | None:
        """Reference level of a line, if the analysis has one."""
        return (
            None
            if self.level is None
            else self.level.slice_ms(line.start_ms, line.end_ms)
        )


@dataclass(frozen=True)
class LineScorer:
    """Scores lines in one mode with the tolerances of one difficulty.

    Attributes:
        mode: Melody (pitch) or rhythm (rap).
        melody: Pitch scoring parameters.
        rhythm: Rhythm scoring parameters.
    """

    mode: ScoringMode
    melody: ScoringConfig
    rhythm: RhythmConfig

    @classmethod
    def create(
        cls,
        mode: ScoringMode,
        difficulty: Difficulty,
        melody: ScoringConfig | None = None,
        rhythm: RhythmConfig | None = None,
    ) -> "LineScorer":
        """A scorer for a mode and difficulty, on top of base parameters."""
        return cls(
            mode=mode,
            melody=scoring_config(difficulty, melody),
            rhythm=rhythm_config(difficulty, rhythm),
        )

    def check(self, reference: SongReference) -> None:
        """Raise if the analysis cannot be scored in this mode.

        Raises:
            RhythmUnavailableError: Rap mode on an analysis without level.
        """
        if self.mode is ScoringMode.RHYTHM and reference.level is None:
            raise RhythmUnavailableError(
                "This song has no vocals' level yet: run the 'level' and "
                "'persist' stages to enable rap mode"
            )

    def score(
        self,
        reference: SongReference,
        line: LyricLine,
        sung: SungPitch,
        latency_ms: float,
    ) -> LineResult:
        """Score a sung line (CPU-bound: run it off the event loop).

        Raises:
            RhythmUnavailableError: Rap mode on an analysis without level.
            MissingLevelError: Rap mode without the microphone level.
        """
        if self.mode is ScoringMode.MELODY:
            return score_line(
                reference.line_pitch(line),
                np.asarray(sung.f0_hz, dtype=np.float64),
                sung.hop_ms,
                latency_ms=latency_ms,
                config=self.melody,
            )
        return self._rhythm(reference, line, sung, latency_ms).result

    def analyze(
        self,
        reference: SongReference,
        line: LyricLine,
        sung: SungPitch,
        latency_ms: float,
    ) -> LineScoring:
        """Score a sung line and explain it (CPU-bound).

        Raises:
            RhythmUnavailableError: Rap mode on an analysis without level.
            MissingLevelError: Rap mode without the microphone level.
        """
        if self.mode is ScoringMode.MELODY:
            analysis = analyze_line(
                reference.line_pitch(line),
                np.asarray(sung.f0_hz, dtype=np.float64),
                sung.hop_ms,
                latency_ms=latency_ms,
                config=self.melody,
            )
            return LineScoring(mode=self.mode, analysis=analysis, rhythm=None)
        rhythm = self._rhythm(reference, line, sung, latency_ms)
        return LineScoring(mode=self.mode, analysis=None, rhythm=rhythm)

    def silence(self, reference: SongReference, line: LyricLine) -> LineResult:
        """Result of a line nobody sang: 0 if scorable (cheap, no alignment)."""
        if self.mode is ScoringMode.MELODY:
            return score_line(
                reference.line_pitch(line),
                np.zeros(0),
                self.melody.scoring_hop_ms,
                config=self.melody,
            )
        level = self._reference_level(reference, line)
        return analyze_rhythm(
            level, np.full(1, SILENT_DB), level.hop_ms, config=self.rhythm
        ).result

    def _reference_level(self, reference: SongReference, line: LyricLine) -> LevelCurve:
        self.check(reference)
        level = reference.line_level(line)
        assert level is not None  # checked above
        return level

    def _rhythm(
        self,
        reference: SongReference,
        line: LyricLine,
        sung: SungPitch,
        latency_ms: float,
    ) -> RhythmAnalysis:
        level = self._reference_level(reference, line)
        if sung.level_db is None:
            raise MissingLevelError(
                "Rap mode needs the microphone level (level_db) of each frame"
            )
        return analyze_rhythm(
            level,
            np.asarray(sung.level_db, dtype=np.float64),
            sung.hop_ms,
            latency_ms=latency_ms,
            config=self.rhythm,
        )
