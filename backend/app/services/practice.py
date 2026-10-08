"""Line analysis of a play session: practice charts and admin diagnostics."""

import asyncio
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Annotated

import numpy as np
from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LineScore, PlaySession
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.repositories.songs import SongAnalysisRepository
from app.db.session import get_db_session
from app.schemas.analysis import LyricLine, PipelineInfo, PitchCurve
from app.schemas.practice import (
    LineAttempt,
    LineDiagnostics,
    LinePractice,
    PracticeWord,
    WordDiagnostics,
)
from app.schemas.sessions import SungPitch
from app.scoring.analysis import LineAnalysis, analyze_line
from app.scoring.difficulty import scoring_config
from app.scoring.line_score import ScoringConfig
from app.services.errors import SongNotFoundError
from app.services.play_sessions import SessionNotFoundError, UnknownLineError
from app.services.voicing import voiced_ratios

_LINES = TypeAdapter(list[LyricLine])


@dataclass
class _LoadedLine:
    """A line of a session with everything needed to analyze it.

    Attributes:
        play_session: The session.
        line: The lyric line.
        song_pitch: Reference pitch of the whole song.
        scored: The stored line score, None if the line was not sung.
        scoring: Scoring parameters of the session's difficulty.
    """

    play_session: PlaySession
    line: LyricLine
    song_pitch: PitchCurve
    scored: LineScore | None
    scoring: ScoringConfig

    @property
    def pitch(self) -> PitchCurve:
        """Reference pitch of the line, as used for scoring."""
        return self.song_pitch.slice_ms(self.line.start_ms, self.line.end_ms)


class PracticeService:
    """Explains how each line of a session was sung."""

    def __init__(
        self, session: AsyncSession, scoring: ScoringConfig | None = None
    ) -> None:
        """Initialize the service.

        Args:
            session: Database session (read only).
            scoring: Base scoring parameters, as in ``PlaySessionService``.
        """
        self._scoring = scoring or ScoringConfig()
        self._analyses = SongAnalysisRepository(session)
        self._play_sessions = PlaySessionRepository(session)

    async def practice(self, session_id: uuid.UUID, line_index: int) -> LinePractice:
        """Analyze one line for the practice chart.

        Args:
            session_id: Id of the session.
            line_index: Line to analyze.

        Returns:
            The line and, when its sung curve is stored, its analysis.

        Raises:
            SessionNotFoundError: If the session does not exist.
            UnknownLineError: If the line does not exist.
        """
        return await self._practice(await self._load(session_id, line_index))

    async def diagnostics(
        self, session_id: uuid.UUID, line_index: int
    ) -> LineDiagnostics:
        """Analyze one line with everything needed to debug it.

        Args:
            session_id: Id of the session.
            line_index: Line to analyze.

        Returns:
            The practice analysis plus the raw inputs, parameters and timing.

        Raises:
            SessionNotFoundError: If the session does not exist.
            UnknownLineError: If the line does not exist.
        """
        loaded = await self._load(session_id, line_index)
        practice = await self._practice(loaded)
        metadata = await self._analyses.get_metadata(loaded.play_session.analysis_id)
        if metadata is None:  # pragma: no cover - guaranteed by the foreign key
            raise SessionNotFoundError(f"Session {session_id} has no analysis")
        version, pipeline = metadata
        line = loaded.line
        ratios = voiced_ratios(
            [(word.start_ms, word.end_ms) for word in line.words],
            loaded.song_pitch,
            loaded.scoring.min_reference_confidence,
        )
        stored = None if loaded.scored is None else loaded.scored.sung_pitch
        return LineDiagnostics(
            **dict(practice),
            latency_ms=loaded.play_session.latency_offset_ms,
            scoring=loaded.scoring,
            analysis_version=version,
            pipeline=PipelineInfo.model_validate(pipeline),
            reference=loaded.pitch,
            sung_input=None if stored is None else SungPitch.model_validate(stored),
            word_timing=[
                WordDiagnostics(
                    text=word.text,
                    start_ms=word.start_ms - line.start_ms,
                    end_ms=word.end_ms - line.start_ms,
                    voiced_ratio=round(float(ratio), 3),
                    probability=word.probability,
                )
                for word, ratio in zip(line.words, ratios, strict=True)
            ],
        )

    async def score_attempt(
        self, song_id: uuid.UUID, line_index: int, attempt: LineAttempt
    ) -> LineAnalysis:
        """Score a practice attempt at one line; nothing is stored.

        Args:
            song_id: Song being practiced.
            line_index: Line sung.
            attempt: Sung pitch, latency, difficulty and the analysis used.

        Returns:
            The analysis of the attempt, as for a sung line of a session.

        Raises:
            SongNotFoundError: If the analysis does not exist for the song.
            UnknownLineError: If the line does not exist.
        """
        reference = await self._analyses.get_reference(attempt.analysis_id, song_id)
        if reference is None:
            raise SongNotFoundError(
                f"Analysis {attempt.analysis_id} of song {song_id} does not exist"
            )
        raw_pitch, raw_lines = reference
        lines = _LINES.validate_python(raw_lines)
        if not 0 <= line_index < len(lines):
            raise UnknownLineError(
                f"Line {line_index} does not exist ({len(lines)} lines)"
            )
        line = lines[line_index]
        pitch = PitchCurve.model_validate(raw_pitch).slice_ms(
            line.start_ms, line.end_ms
        )
        return await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                analyze_line,
                pitch,
                np.asarray(attempt.f0_hz, dtype=np.float64),
                attempt.hop_ms,
                latency_ms=attempt.latency_offset_ms,
                config=scoring_config(attempt.difficulty, self._scoring),
            ),
        )

    async def _load(self, session_id: uuid.UUID, line_index: int) -> _LoadedLine:
        play_session = await self._play_sessions.get(session_id)
        if play_session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist")
        reference = await self._analyses.get_reference(play_session.analysis_id)
        if reference is None:  # pragma: no cover - guaranteed by the foreign key
            raise SessionNotFoundError(f"Session {session_id} has no analysis")
        raw_pitch, raw_lines = reference
        lines = _LINES.validate_python(raw_lines)
        if not 0 <= line_index < len(lines):
            raise UnknownLineError(
                f"Line {line_index} does not exist ({len(lines)} lines)"
            )
        return _LoadedLine(
            play_session=play_session,
            line=lines[line_index],
            song_pitch=PitchCurve.model_validate(raw_pitch),
            scored=await self._play_sessions.get_line_score(session_id, line_index),
            scoring=scoring_config(play_session.difficulty, self._scoring),
        )

    async def _practice(self, loaded: _LoadedLine) -> LinePractice:
        line = loaded.line
        practice = LinePractice(
            session_id=loaded.play_session.id,
            line_index=line.index,
            text=line.text,
            start_ms=line.start_ms,
            end_ms=line.end_ms,
            difficulty=loaded.play_session.difficulty,
            words=[
                PracticeWord(
                    text=word.text,
                    start_ms=word.start_ms - line.start_ms,
                    end_ms=word.end_ms - line.start_ms,
                )
                for word in line.words
            ],
            status="not_sung",
            analysis=None,
        )
        if loaded.scored is None:
            return practice
        if loaded.scored.sung_pitch is None:
            return practice.model_copy(update={"status": "not_stored"})
        sung = SungPitch.model_validate(loaded.scored.sung_pitch)
        # DTW is CPU-bound: keep it off the event loop, as live scoring does.
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                analyze_line,
                loaded.pitch,
                np.asarray(sung.f0_hz, dtype=np.float64),
                sung.hop_ms,
                latency_ms=loaded.play_session.latency_offset_ms,
                config=loaded.scoring,
            ),
        )
        return practice.model_copy(update={"status": "analyzed", "analysis": analysis})


def get_practice_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PracticeService:
    """Provide a ``PracticeService`` bound to the request's session.

    Args:
        session: Request-scoped database session.

    Returns:
        The service.
    """
    return PracticeService(session)
