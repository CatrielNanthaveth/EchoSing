"""Persistence of play sessions and their per-line scores."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.db.models import LineScore, PlaySession, SongAnalysis
from app.domain.enums import Difficulty, PlaySessionStatus


class PlaySessionRepository:
    """Data access for ``PlaySession`` and ``LineScore`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    async def add(
        self,
        analysis: SongAnalysis,
        player_name: str,
        latency_offset_ms: int = 0,
        difficulty: Difficulty = Difficulty.NORMAL,
    ) -> PlaySession:
        """Start a play session against a specific analysis.

        The song id is taken from the analysis so both can never disagree.

        Args:
            analysis: Analysis (lyrics + reference pitch) the player sings.
            player_name: Display name of the anonymous player.
            latency_offset_ms: Audio latency measured during calibration.
            difficulty: Pitch tolerance of the scoring.

        Returns:
            The persisted session in ``ACTIVE`` status.
        """
        return await self.start(
            analysis.song_id, analysis.id, player_name, latency_offset_ms, difficulty
        )

    async def start(
        self,
        song_id: uuid.UUID,
        analysis_id: uuid.UUID,
        player_name: str,
        latency_offset_ms: int = 0,
        difficulty: Difficulty = Difficulty.NORMAL,
    ) -> PlaySession:
        """Start a play session from the identity of an analysis.

        Avoids loading the (large) analysis document; the caller must take
        both ids from the same analysis row.

        Args:
            song_id: Id of the song of the analysis.
            analysis_id: Id of the analysis the player sings.
            player_name: Display name of the anonymous player.
            latency_offset_ms: Audio latency measured during calibration.
            difficulty: Pitch tolerance of the scoring.

        Returns:
            The persisted session in ``ACTIVE`` status.
        """
        play_session = PlaySession(
            song_id=song_id,
            analysis_id=analysis_id,
            player_name=player_name,
            latency_offset_ms=latency_offset_ms,
            difficulty=difficulty,
        )
        self._session.add(play_session)
        await self._session.flush()
        return play_session

    async def get(self, session_id: uuid.UUID) -> PlaySession | None:
        """Fetch a play session by id.

        Args:
            session_id: Id of the play session.

        Returns:
            The play session, or None if it does not exist.
        """
        return await self._session.get(PlaySession, session_id)

    async def add_line_score(
        self,
        session_id: uuid.UUID,
        line_index: int,
        score: float | None,
        accuracy: float | None,
        hit: bool,
        *,
        scorable: bool = True,
        voiced_frames: int = 0,
        sung_pitch: dict[str, Any] | None = None,
    ) -> LineScore:
        """Record the score of one lyric line.

        Args:
            session_id: Id of the play session.
            line_index: Zero-based index of the line in the analysis.
            score: Line score in [0, 100]; None if the line is not scorable.
            accuracy: Fraction of in-tune frames in [0, 1]; None if not
                scorable.
            hit: Whether the line counts towards the streak.
            scorable: Whether the reference had enough singing to score it.
            voiced_frames: Sung reference frames (weight in session totals).
            sung_pitch: Pitch the player sang, as sent by the client.

        Returns:
            The persisted line score.

        Raises:
            sqlalchemy.exc.IntegrityError: If the line was already scored, a
                value is out of range, or a scorable line has no score.
        """
        line_score = LineScore(
            session_id=session_id,
            line_index=line_index,
            scorable=scorable,
            score=score,
            accuracy=accuracy,
            hit=hit,
            voiced_frames=voiced_frames,
            sung_pitch=sung_pitch,
        )
        self._session.add(line_score)
        await self._session.flush()
        return line_score

    async def finish(
        self,
        play_session: PlaySession,
        *,
        total_score: float | None,
        accuracy: float | None,
        best_streak: int,
    ) -> None:
        """Record the totals of a session and mark it finished.

        Args:
            play_session: Session to finish.
            total_score: Final score 0-100, None if nothing was scorable.
            accuracy: Final accuracy 0-1, None if nothing was scorable.
            best_streak: Longest run of hit lines.
        """
        play_session.total_score = total_score
        play_session.accuracy = accuracy
        play_session.best_streak = best_streak
        play_session.status = PlaySessionStatus.FINISHED
        play_session.finished_at = datetime.now(UTC)
        await self._session.flush()

    async def get_line_score(
        self, session_id: uuid.UUID, line_index: int
    ) -> LineScore | None:
        """Fetch the score of one line, including the pitch that was sung.

        Args:
            session_id: Id of the play session.
            line_index: Zero-based index of the line.

        Returns:
            The line score, or None if the line was not sung in the session.
        """
        result = await self._session.scalars(
            select(LineScore)
            .options(undefer(LineScore.sung_pitch))
            .where(
                LineScore.session_id == session_id,
                LineScore.line_index == line_index,
            )
        )
        return result.one_or_none()

    async def list_line_scores(self, session_id: uuid.UUID) -> Sequence[LineScore]:
        """List the scores of a play session ordered by line.

        Args:
            session_id: Id of the play session.

        Returns:
            The line scores, by ascending line index.
        """
        result = await self._session.scalars(
            select(LineScore)
            .where(LineScore.session_id == session_id)
            .order_by(LineScore.line_index)
        )
        return result.all()
