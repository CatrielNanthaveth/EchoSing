"""Persistence of play sessions and their per-line scores."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LineScore, PlaySession, SongAnalysis


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
    ) -> PlaySession:
        """Start a play session against a specific analysis.

        The song id is taken from the analysis so both can never disagree.

        Args:
            analysis: Analysis (lyrics + reference pitch) the player sings.
            player_name: Display name of the anonymous player.
            latency_offset_ms: Audio latency measured during calibration.

        Returns:
            The persisted session in ``ACTIVE`` status.
        """
        return await self.start(
            analysis.song_id, analysis.id, player_name, latency_offset_ms
        )

    async def start(
        self,
        song_id: uuid.UUID,
        analysis_id: uuid.UUID,
        player_name: str,
        latency_offset_ms: int = 0,
    ) -> PlaySession:
        """Start a play session from the identity of an analysis.

        Avoids loading the (large) analysis document; the caller must take
        both ids from the same analysis row.

        Args:
            song_id: Id of the song of the analysis.
            analysis_id: Id of the analysis the player sings.
            player_name: Display name of the anonymous player.
            latency_offset_ms: Audio latency measured during calibration.

        Returns:
            The persisted session in ``ACTIVE`` status.
        """
        play_session = PlaySession(
            song_id=song_id,
            analysis_id=analysis_id,
            player_name=player_name,
            latency_offset_ms=latency_offset_ms,
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
        )
        self._session.add(line_score)
        await self._session.flush()
        return line_score

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
