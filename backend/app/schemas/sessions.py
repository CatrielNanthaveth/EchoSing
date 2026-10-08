"""Schemas of play sessions (REST)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """Request to start singing a song.

    Attributes:
        song_id: Song to sing (must be playable).
        player_name: Display name of the anonymous player.
        latency_offset_ms: Audio latency measured by the client's calibration;
            positive when the voice arrives late.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    song_id: uuid.UUID
    player_name: str = Field(min_length=1, max_length=50)
    latency_offset_ms: int = Field(default=0, ge=-500, le=1000)


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
    """

    session_id: uuid.UUID
    song_id: uuid.UUID
    analysis_id: uuid.UUID
    analysis_version: int
    line_count: int
    player_name: str
    latency_offset_ms: int
