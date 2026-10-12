"""Line analysis of a play session: practice charts, attempts and diagnostics."""

import asyncio
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LineScore, PlaySession
from app.db.repositories.play_sessions import PlaySessionRepository
from app.db.repositories.songs import SongAnalysisRepository
from app.db.session import get_db_session
from app.schemas.analysis import LyricLine, PipelineInfo
from app.schemas.practice import (
    LineAttempt,
    LineDiagnostics,
    LinePractice,
    LineScoring,
    PracticeWord,
    WordDiagnostics,
)
from app.schemas.sessions import SungPitch
from app.scoring.line_score import ScoringConfig
from app.scoring.rhythm import RhythmConfig
from app.services.errors import SongNotFoundError
from app.services.line_scoring import LineScorer, SongReference
from app.services.play_sessions import SessionNotFoundError, UnknownLineError
from app.services.voicing import voiced_ratios


@dataclass
class _LoadedLine:
    """A line of a session with everything needed to analyze it.

    Attributes:
        play_session: The session.
        reference: Lines and reference curves of the session's analysis.
        line: The lyric line.
        scored: The stored line score, None if the line was not sung.
        scorer: Scores in the session's mode and difficulty.
    """

    play_session: PlaySession
    reference: SongReference
    line: LyricLine
    scored: LineScore | None
    scorer: LineScorer


def _line(reference: SongReference, line_index: int) -> LyricLine:
    if not 0 <= line_index < len(reference.lines):
        raise UnknownLineError(
            f"Line {line_index} does not exist ({len(reference.lines)} lines)"
        )
    return reference.lines[line_index]


class PracticeService:
    """Explains how each line of a session was sung, and scores attempts."""

    def __init__(
        self,
        session: AsyncSession,
        scoring: ScoringConfig | None = None,
        rhythm: RhythmConfig | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            session: Database session (read only).
            scoring: Base pitch scoring parameters, as in ``PlaySessionService``.
            rhythm: Base rhythm (rap mode) parameters, likewise.
        """
        self._scoring = scoring or ScoringConfig()
        self._rhythm = rhythm or RhythmConfig()
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
            loaded.reference.pitch,
            loaded.scorer.melody.min_reference_confidence,
        )
        stored = None if loaded.scored is None else loaded.scored.sung_pitch
        return LineDiagnostics(
            **dict(practice),
            latency_ms=loaded.play_session.latency_offset_ms,
            scoring=loaded.scorer.melody,
            rhythm_scoring=loaded.scorer.rhythm,
            analysis_version=version,
            pipeline=PipelineInfo.model_validate(pipeline),
            reference=loaded.reference.line_pitch(line),
            reference_level=loaded.reference.line_level(line),
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
    ) -> LineScoring:
        """Score a practice attempt at one line; nothing is stored.

        Args:
            song_id: Song being practiced.
            line_index: Line sung.
            attempt: Sung curves, latency, difficulty, mode and the analysis.

        Returns:
            The attempt scored and explained in its mode.

        Raises:
            SongNotFoundError: If the analysis does not exist for the song.
            UnknownLineError: If the line does not exist.
            app.services.line_scoring.RhythmUnavailableError: Rap mode on an
                analysis without the vocals' level.
        """
        raw = await self._analyses.get_reference(attempt.analysis_id, song_id)
        if raw is None:
            raise SongNotFoundError(
                f"Analysis {attempt.analysis_id} of song {song_id} does not exist"
            )
        reference = SongReference.from_raw(raw)
        line = _line(reference, line_index)
        scorer = LineScorer.create(
            attempt.mode, attempt.difficulty, self._scoring, self._rhythm
        )
        scorer.check(reference)
        sung = SungPitch(
            hop_ms=attempt.hop_ms, f0_hz=attempt.f0_hz, level_db=attempt.level_db
        )
        return await asyncio.get_running_loop().run_in_executor(
            None,
            partial(scorer.analyze, reference, line, sung, attempt.latency_offset_ms),
        )

    async def _load(self, session_id: uuid.UUID, line_index: int) -> _LoadedLine:
        play_session = await self._play_sessions.get(session_id)
        if play_session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist")
        raw = await self._analyses.get_reference(play_session.analysis_id)
        if raw is None:  # pragma: no cover - guaranteed by the foreign key
            raise SessionNotFoundError(f"Session {session_id} has no analysis")
        reference = SongReference.from_raw(raw)
        return _LoadedLine(
            play_session=play_session,
            reference=reference,
            line=_line(reference, line_index),
            scored=await self._play_sessions.get_line_score(session_id, line_index),
            scorer=LineScorer.create(
                play_session.mode,
                play_session.difficulty,
                self._scoring,
                self._rhythm,
            ),
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
            mode=loaded.play_session.mode,
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
            rhythm=None,
        )
        if loaded.scored is None:
            return practice
        if loaded.scored.sung_pitch is None:
            return practice.model_copy(update={"status": "not_stored"})
        sung = SungPitch.model_validate(loaded.scored.sung_pitch)
        # Scoring is CPU-bound: keep it off the event loop, as live scoring does.
        scoring = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                loaded.scorer.analyze,
                loaded.reference,
                line,
                sung,
                loaded.play_session.latency_offset_ms,
            ),
        )
        return practice.model_copy(
            update={
                "status": "analyzed",
                "analysis": scoring.analysis,
                "rhythm": scoring.rhythm,
            }
        )


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
