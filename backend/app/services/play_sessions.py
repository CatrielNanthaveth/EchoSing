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
    LineReport,
    LineScoreMessage,
    SessionCreate,
    SessionCreated,
    SessionResults,
    SessionTotals,
)
from app.scoring.difficulty import scoring_config
from app.scoring.line_score import LineResult, ScoringConfig, score_line
from app.scoring.session import current_streak, summarize_session
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
        scoring: Scoring parameters of the session's difficulty.
        lines: Lyric lines of the analysis.
        pitch: Reference pitch curve of the whole song.
        results: Results of the lines scored so far, by line index.
    """

    session_id: uuid.UUID
    analysis_id: uuid.UUID
    latency_ms: int
    scoring: ScoringConfig
    lines: list[LyricLine]
    pitch: PitchCurve
    results: dict[int, LineResult] = field(default_factory=dict)


def _line_report(
    line: LyricLine, sung: bool, results: dict[int, LineResult]
) -> LineReport:
    result = results.get(line.index)
    return LineReport(
        line_index=line.index,
        text=line.text,
        sung=sung,
        scorable=None if result is None else result.scorable,
        score=None if result is None else result.score,
        accuracy=None if result is None else result.accuracy,
        hit=False if result is None else result.hit,
    )


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
            scoring: Base scoring parameters; each session applies the pitch
                tolerance of its difficulty on top.
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
            scoring=scoring_config(play_session.difficulty, self._scoring),
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
                config=live.scoring,
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

    @staticmethod
    def _with_unsung_lines(
        lines: list[LyricLine],
        pitch: PitchCurve,
        sung: dict[int, LineResult],
        scoring: ScoringConfig,
    ) -> dict[int, LineResult]:
        """Results of every line, scoring the unsung ones as silence (0).

        Scoring silence is cheap (no alignment) and tells whether each unsung
        line would have counted. Unsung lines are never stored, so reports can
        tell "sung badly" from "not sung".
        """
        complete = dict(sung)
        for line in lines:
            if line.index not in complete:
                complete[line.index] = score_line(
                    pitch.slice_ms(line.start_ms, line.end_ms),
                    np.zeros(0),
                    scoring.scoring_hop_ms,
                    config=scoring,
                )
        return complete

    async def finish(self, live: LiveSession) -> SessionTotals:
        """Close a session: totals count unsung lines as 0 and are stored.

        Without counting unsung lines, singing a single line perfectly would
        give a perfect total.

        Args:
            live: Open session.

        Returns:
            The final totals.

        Raises:
            SessionNotFoundError: If the session disappeared meanwhile.
        """
        play_session = await self._play_sessions.get(live.session_id)
        if play_session is None:  # pragma: no cover - sessions are never deleted
            raise SessionNotFoundError(f"Session {live.session_id} does not exist")
        complete = self._with_unsung_lines(
            live.lines, live.pitch, live.results, live.scoring
        )
        summary = summarize_session([complete[i] for i in sorted(complete)])
        await self._play_sessions.finish(
            play_session,
            total_score=summary.total_score,
            accuracy=summary.accuracy,
            best_streak=summary.best_streak,
        )
        await self._session.commit()
        return SessionTotals.model_validate(summary.model_dump())

    async def get_results(self, session_id: uuid.UUID) -> SessionResults:
        """Report a session: totals and the result of every line.

        Args:
            session_id: Id of the session.

        Returns:
            The report. For an active session, totals cover the lines sung so
            far and unsung lines have no result yet; once finished, unsung
            lines score 0, as in the stored totals.

        Raises:
            SessionNotFoundError: If the session does not exist.
        """
        play_session = await self._play_sessions.get(session_id)
        if play_session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist")
        reference = await self._analyses.get_reference(play_session.analysis_id)
        if reference is None:  # pragma: no cover - guaranteed by the foreign key
            raise SessionNotFoundError(f"Session {session_id} has no analysis")
        raw_pitch, raw_lines = reference
        lines = _LINES.validate_python(raw_lines)
        sung = {
            row.line_index: _result_from_row(
                row.scorable, row.score, row.accuracy, row.hit, row.voiced_frames
            )
            for row in await self._play_sessions.list_line_scores(session_id)
        }
        finished = play_session.status is PlaySessionStatus.FINISHED
        results = (
            self._with_unsung_lines(
                lines,
                PitchCurve.model_validate(raw_pitch),
                sung,
                scoring_config(play_session.difficulty, self._scoring),
            )
            if finished
            else sung
        )
        summary = summarize_session([results[i] for i in sorted(results)])
        return SessionResults(
            session_id=play_session.id,
            song_id=play_session.song_id,
            analysis_id=play_session.analysis_id,
            player_name=play_session.player_name,
            difficulty=play_session.difficulty,
            status=play_session.status,
            started_at=play_session.started_at,
            finished_at=play_session.finished_at,
            totals=SessionTotals.model_validate(summary.model_dump()),
            lines=[_line_report(line, line.index in sung, results) for line in lines],
        )

    async def create(self, request: SessionCreate) -> SessionCreated:
        """Start a play session on the current analysis of a playable song.

        Args:
            request: Song, player name, measured latency and difficulty.

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
            request.difficulty,
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
            difficulty=play_session.difficulty,
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
