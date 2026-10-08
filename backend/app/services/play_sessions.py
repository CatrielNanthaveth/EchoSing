"""Karaoke play sessions: start, score lines, finish and report."""

import asyncio
import uuid
from dataclasses import dataclass, field
from functools import partial
from typing import Annotated

import numpy as np
from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.catalog import CatalogRepository
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.repositories.songs import SongAnalysisRepository
from app.db.session import get_db_session
from app.domain.enums import PlaySessionStatus
from app.schemas.analysis import LyricLine, PitchCurve
from app.schemas.sessions import (
    LinePitchMessage,
    LineScoreMessage,
    SessionCreate,
    SessionCreated,
)
from app.scoring.line_score import LineResult, ScoringConfig, score_line
from app.scoring.session import current_streak
from app.services.errors import SongNotFoundError

_LINES = TypeAdapter(list[LyricLine])


class SessionNotFoundError(Exception):
    """The play session does not exist."""


class SessionFinishedError(Exception):
    """The play session is already finished."""


class UnknownLineError(Exception):
    """The line index does not exist in the session's analysis."""


class LineAlreadyScoredError(Exception):
    """The line was already scored in this session."""


@dataclass
class LiveSession:
    """A session open for real-time scoring, with its reference in memory.

    Attributes:
        session_id: Id of the session.
        analysis_id: Analysis the session is scored against.
        latency_ms: Latency compensated when scoring.
        lines: Lyric lines of the analysis.
        pitch: Reference pitch curve of the whole song.
        results: Results of the lines scored so far, by line index.
    """

    session_id: uuid.UUID
    analysis_id: uuid.UUID
    latency_ms: int
    lines: list[LyricLine]
    pitch: PitchCurve
    results: dict[int, LineResult] = field(default_factory=dict)


def _result_from_row(
    scorable: bool,
    score: float | None,
    accuracy: float | None,
    hit: bool,
    voiced_frames: int,
) -> LineResult:
    return LineResult(
        scorable=scorable,
        score=score,
        accuracy=accuracy,
        hit=hit,
        voiced_frames=voiced_frames,
    )


class PlaySessionService:
    """Manages the lifecycle of play sessions."""

    def __init__(
        self, session: AsyncSession, scoring: ScoringConfig | None = None
    ) -> None:
        """Initialize the service.

        Args:
            session: Database session; this service commits its own changes.
            scoring: Scoring parameters.
        """
        self._session = session
        self._scoring = scoring or ScoringConfig()
        self._catalog = CatalogRepository(session)
        self._analyses = SongAnalysisRepository(session)
        self._play_sessions = PlaySessionRepository(session)

    async def open(self, session_id: uuid.UUID) -> LiveSession:
        """Load an active session and its reference for real-time scoring.

        Args:
            session_id: Id of the session.

        Returns:
            The live session, including lines already scored (reconnection).

        Raises:
            SessionNotFoundError: If the session does not exist.
            SessionFinishedError: If the session is already finished.
        """
        play_session = await self._play_sessions.get(session_id)
        if play_session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist")
        if play_session.status is PlaySessionStatus.FINISHED:
            raise SessionFinishedError(f"Session {session_id} is already finished")
        reference = await self._analyses.get_reference(play_session.analysis_id)
        if reference is None:  # pragma: no cover - guaranteed by the foreign key
            raise SessionNotFoundError(f"Session {session_id} has no analysis")
        raw_pitch, raw_lines = reference
        scored = await self._play_sessions.list_line_scores(session_id)
        return LiveSession(
            session_id=session_id,
            analysis_id=play_session.analysis_id,
            latency_ms=play_session.latency_offset_ms,
            lines=_LINES.validate_python(raw_lines),
            pitch=PitchCurve.model_validate(raw_pitch),
            results={
                row.line_index: _result_from_row(
                    row.scorable, row.score, row.accuracy, row.hit, row.voiced_frames
                )
                for row in scored
            },
        )

    async def score_line(
        self, live: LiveSession, message: LinePitchMessage
    ) -> LineScoreMessage:
        """Score a sung line, store the result and report the live streak.

        Scoring is CPU-bound, so it runs in a worker thread off the event loop.

        Args:
            live: Open session.
            message: Pitch sung over the line.

        Returns:
            The line score and the current streak.

        Raises:
            UnknownLineError: If the line does not exist.
            LineAlreadyScoredError: If the line was already scored.
        """
        index = message.line_index
        if index >= len(live.lines):
            raise UnknownLineError(
                f"Line {index} does not exist ({len(live.lines)} lines)"
            )
        if index in live.results:
            raise LineAlreadyScoredError(f"Line {index} was already scored")

        line = live.lines[index]
        reference = live.pitch.slice_ms(line.start_ms, line.end_ms)
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                score_line,
                reference,
                np.asarray(message.f0_hz, dtype=np.float64),
                message.hop_ms,
                latency_ms=live.latency_ms,
                config=self._scoring,
            ),
        )

        try:
            await self._play_sessions.add_line_score(
                live.session_id,
                index,
                result.score,
                result.accuracy,
                result.hit,
                scorable=result.scorable,
                voiced_frames=result.voiced_frames,
            )
            await self._session.commit()
        except IntegrityError as error:  # scored concurrently by another socket
            await self._session.rollback()
            raise LineAlreadyScoredError(f"Line {index} was already scored") from error

        live.results[index] = result
        return LineScoreMessage(
            line_index=index,
            scorable=result.scorable,
            score=result.score,
            accuracy=result.accuracy,
            hit=result.hit,
            streak=current_streak(live.results, index),
        )

    async def create(self, request: SessionCreate) -> SessionCreated:
        """Start a play session on the current analysis of a playable song.

        Args:
            request: Song, player name and measured latency.

        Returns:
            The session and what will be sung.

        Raises:
            SongNotFoundError: If the song does not exist or is not playable.
        """
        playable = await self._catalog.get_playable(request.song_id)
        identity = await self._analyses.get_current_identity(request.song_id)
        if playable is None or identity is None:
            raise SongNotFoundError(f"Song {request.song_id} is not available")
        analysis_id, version = identity

        play_session = await self._play_sessions.start(
            request.song_id,
            analysis_id,
            request.player_name,
            request.latency_offset_ms,
        )
        await self._session.commit()
        return SessionCreated(
            session_id=play_session.id,
            song_id=request.song_id,
            analysis_id=analysis_id,
            analysis_version=version,
            line_count=playable.line_count,
            player_name=play_session.player_name,
            latency_offset_ms=play_session.latency_offset_ms,
        )


def get_play_session_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlaySessionService:
    """Provide a ``PlaySessionService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return PlaySessionService(session)
