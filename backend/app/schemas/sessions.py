"""Schemas of play sessions: REST bodies and WebSocket messages."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Difficulty, PlaySessionStatus


class SessionCreate(BaseModel):
    """Request to start singing a song.

    Attributes:
        song_id: Song to sing (must be playable).
        player_name: Display name of the anonymous player.
        latency_offset_ms: Audio latency measured by the client's calibration;
            positive when the voice arrives late.
        difficulty: Pitch tolerance of the scoring.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    song_id: uuid.UUID
    player_name: str = Field(min_length=1, max_length=50)
    latency_offset_ms: int = Field(default=0, ge=-500, le=1000)
    difficulty: Difficulty = Difficulty.NORMAL


class SessionCreated(BaseModel):
    """A started play session.

    Attributes:
        session_id: Id of the session (used by the WebSocket).
        song_id: Song being sung.
        analysis_id: Analysis version the session is scored against.
        analysis_version: Version number of that analysis.
        line_count: Number of lyric lines to sing.
        player_name: Display name of the player.
        latency_offset_ms: Latency applied when scoring.
        difficulty: Pitch tolerance of the scoring.
    """

    session_id: uuid.UUID
    song_id: uuid.UUID
    analysis_id: uuid.UUID
    analysis_version: int
    line_count: int
    player_name: str
    latency_offset_ms: int
    difficulty: Difficulty


# --- WebSocket messages (see docs/ws-protocol.md) ---------------------------------

MAX_PITCH_FRAMES = 6000
"""At most 60 s of pitch at 10 ms per line message."""


class LinePitchMessage(BaseModel):
    """Client -> server: the pitch the player sang over one line.

    Attributes:
        type: Message type.
        line_index: Line that was sung.
        hop_ms: Time between pitch frames.
        f0_hz: Pitch per frame in Hz, from the line start (0 = no voice). Send a
            little more than the line (~300 ms) for latency compensation.
    """

    type: Literal["line_pitch"]
    line_index: int = Field(ge=0)
    hop_ms: float = Field(ge=5, le=50)
    f0_hz: list[Annotated[float, Field(ge=0, le=5000)]] = Field(
        max_length=MAX_PITCH_FRAMES
    )


class ReadyMessage(BaseModel):
    """Server -> client: the session is open and ready to score lines.

    Attributes:
        type: Message type.
        session_id: Id of the session.
        analysis_id: Analysis the lines are scored against.
        line_count: Number of lyric lines.
        scored_lines: Lines already scored (when reconnecting).
    """

    type: Literal["ready"] = "ready"
    session_id: uuid.UUID
    analysis_id: uuid.UUID
    line_count: int
    scored_lines: list[int]


class LineScoreMessage(BaseModel):
    """Server -> client: the score of a sung line.

    Attributes:
        type: Message type.
        line_index: Line that was scored.
        scorable: False when the line has too little singing to judge.
        score: 0-100, None if not scorable.
        accuracy: Fraction of in-tune frames, None if not scorable.
        hit: Whether the line counts towards the streak.
        streak: Consecutive hits ending at this line.
    """

    type: Literal["line_score"] = "line_score"
    line_index: int
    scorable: bool
    score: float | None
    accuracy: float | None
    hit: bool
    streak: int


class ErrorCode(StrEnum):
    """Machine-readable error codes sent over the WebSocket."""

    INVALID_MESSAGE = "invalid_message"
    UNKNOWN_LINE = "unknown_line"
    LINE_ALREADY_SCORED = "line_already_scored"


class ErrorMessage(BaseModel):
    """Server -> client: a message could not be processed (connection stays open).

    Attributes:
        type: Message type.
        code: What went wrong.
        detail: Human-readable explanation.
    """

    type: Literal["error"] = "error"
    code: ErrorCode
    detail: str


class FinishMessage(BaseModel):
    """Client -> server: the song is over; compute the totals and close.

    Attributes:
        type: Message type.
    """

    type: Literal["finish"]


ClientMessage = Annotated[LinePitchMessage | FinishMessage, Field(discriminator="type")]
"""Any message a client may send."""


class SessionTotals(BaseModel):
    """Totals of a performance.

    Attributes:
        total_score: 0-100 weighted by line length; None if nothing scorable.
        accuracy: Fraction of in-tune frames; None if nothing scorable.
        best_streak: Longest run of consecutive hit lines.
        scored_lines: Scorable lines included.
        hit_lines: Lines that were hits.
    """

    total_score: float | None
    accuracy: float | None
    best_streak: int
    scored_lines: int
    hit_lines: int


class SessionSummaryMessage(SessionTotals):
    """Server -> client: final totals, sent right before closing.

    Attributes:
        type: Message type.
    """

    type: Literal["session_summary"] = "session_summary"


class LineReport(BaseModel):
    """Result of one lyric line in a session report.

    Attributes:
        line_index: Line index.
        text: Line text.
        sung: Whether the player sang it (unsung lines score 0 at finish).
        scorable: Whether the line has enough singing to be judged.
        score: 0-100, None if not sung yet or not scorable.
        accuracy: 0-1, None if not sung yet or not scorable.
        hit: Whether the line was a hit.
    """

    line_index: int
    text: str
    sung: bool
    scorable: bool | None
    score: float | None
    accuracy: float | None
    hit: bool


class SessionResults(BaseModel):
    """Report of a play session.

    Attributes:
        session_id: Session id.
        song_id: Song sung.
        analysis_id: Analysis the session was scored against.
        player_name: Display name of the player.
        difficulty: Pitch tolerance the session is scored with.
        status: ``active`` or ``finished``.
        started_at: When the session started.
        finished_at: When it finished, if it did.
        totals: Totals over the lines scored so far (all lines once finished).
        lines: One entry per lyric line, in order.
    """

    session_id: uuid.UUID
    song_id: uuid.UUID
    analysis_id: uuid.UUID
    player_name: str
    difficulty: Difficulty
    status: PlaySessionStatus
    started_at: datetime
    finished_at: datetime | None
    totals: SessionTotals
    lines: list[LineReport]
