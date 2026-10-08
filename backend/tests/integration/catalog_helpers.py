"""Helpers to create playable songs in integration tests."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongAnalysisRepository, SongRepository
from app.domain.enums import AssetKind, SongStatus
from app.schemas.analysis import FORMAT_VERSION
from app.storage.keys import asset_key
from app.storage.local import LocalStorage

INSTRUMENTAL = bytes(range(256)) * 40  # 10 240 fake "MP3" bytes


async def add_song(
    session: AsyncSession,
    storage: LocalStorage,
    analysis_json: dict[str, Any],
    title: str,
    artist: str = "Artist",
    *,
    status: SongStatus = SongStatus.READY,
    analysis: bool = True,
    instrumental: bool = True,
) -> uuid.UUID:
    """Create a song with (optionally) its instrumental and current analysis."""
    songs = SongRepository(session)
    song = await songs.add(title, artist, "es")
    await songs.set_duration(song.id, analysis_json["duration_ms"])
    await songs.set_status(song.id, status)
    if instrumental:
        stored = await storage.save(
            asset_key(song.id, AssetKind.INSTRUMENTAL, "mp3"),
            INSTRUMENTAL,
            "audio/mpeg",
        )
        await SongAssetRepository(session).add(song.id, AssetKind.INSTRUMENTAL, stored)
    if analysis:
        await SongAnalysisRepository(session).add_version(
            song.id, FORMAT_VERSION, analysis_json
        )
    await session.commit()
    return song.id
