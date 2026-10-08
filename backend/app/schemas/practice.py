"""Schemas of the line analysis: practice charts and admin diagnostics."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.domain.enums import Difficulty
from app.schemas.analysis import PipelineInfo, PitchCurve
from app.schemas.sessions import MAX_PITCH_FRAMES, SungPitch
from app.scoring.analysis import LineAnalysis
from app.scoring.line_score import ScoringConfig

AnalysisStatus = Literal["analyzed", "not_sung", "not_stored"]
"""``not_sung``: the line was not sung; ``not_stored``: sung before curves were
kept, so it can no longer be analyzed."""


class LineAttempt(BaseModel):
    """A practice attempt at one line, scored but not stored.

    Attributes:
        analysis_id: Analysis whose lines and pitch the client is using.
        hop_ms: Time between pitch frames.
        f0_hz: Pitch per frame in Hz from the line start (0 = no voice), as in
            the ``line_pitch`` message (send ~300 ms past the line end).
        latency_offset_ms: Latency measured by the client's calibration.
        difficulty: Pitch tolerance.
    """

    analysis_id: uuid.UUID
    hop_ms: float = Field(ge=5, le=50)
    f0_hz: list[Annotated[float, Field(ge=0, le=5000)]] = Field(
        max_length=MAX_PITCH_FRAMES
    )
    latency_offset_ms: int = Field(default=0, ge=-500, le=1000)
    difficulty: Difficulty = Difficulty.NORMAL


class PracticeWord(BaseModel):
    """A lyric word, timed from the line start.

    Attributes:
        text: Word as displayed.
        start_ms: Start, relative to the line start.
        end_ms: End, relative to the line start.
    """

    text: str
    start_ms: int
    end_ms: int


class LinePractice(BaseModel):
    """How the player sang one line, for the practice chart.

    Attributes:
        session_id: Session.
        line_index: Line.
        text: Line text.
        start_ms: Line start in the song.
        end_ms: Line end in the song.
        difficulty: Pitch tolerance the line was scored with.
        words: Words of the line.
        status: Whether there is an analysis (see ``AnalysisStatus``).
        analysis: Curves, alignment and offsets; None unless ``analyzed``.
    """

    session_id: uuid.UUID
    line_index: int
    text: str
    start_ms: int
    end_ms: int
    difficulty: Difficulty
    words: list[PracticeWord]
    status: AnalysisStatus
    analysis: LineAnalysis | None


class WordDiagnostics(PracticeWord):
    """A word with what is known about its timing.

    Attributes:
        voiced_ratio: Fraction of the word's span where the reference vocals
            have voice. Low values on sung words point to lyrics out of sync.
        probability: Transcriber confidence, None for official lyrics words
            without a transcribed match.
    """

    voiced_ratio: float
    probability: float | None


class LineDiagnostics(LinePractice):
    """Everything behind a line score, for admins debugging sync and scoring.

    Attributes:
        latency_ms: Latency compensated for the session.
        scoring: Exact scoring parameters used (difficulty included).
        analysis_version: Version of the song analysis the session uses.
        pipeline: Models that produced that analysis.
        reference: Reference pitch of the line at its native resolution
            (frame 0 at ``start_ms``).
        sung_input: Pitch exactly as the client sent it, None if not stored.
        word_timing: Words with their voicing and transcriber confidence.
    """

    latency_ms: int
    scoring: ScoringConfig
    analysis_version: int
    pipeline: PipelineInfo
    reference: PitchCurve
    sung_input: SungPitch | None
    word_timing: list[WordDiagnostics]
