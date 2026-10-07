"""Persistence of song audio assets."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SongAsset
from app.domain.enums import AssetKind
from app.storage.base import StoredObject


class SongAssetRepository:
    """Data access for ``SongAsset`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Session used for every query.
        """
        self._session = session

    async def add(
        self, song_id: uuid.UUID, kind: AssetKind, stored: StoredObject
    ) -> SongAsset:
        """Register a stored file as an asset of a song.

        Args:
            song_id: Id of the song.
            kind: Kind of asset.
            stored: Metadata returned by the storage backend.

        Returns:
            The persisted asset.
        """
        asset = SongAsset(
            song_id=song_id,
            kind=kind,
            storage_key=stored.key,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
        )
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def upsert(
        self, song_id: uuid.UUID, kind: AssetKind, stored: StoredObject
    ) -> SongAsset:
        """Register a stored file, replacing the song's asset of the same kind.

        Used when (re)processing a song regenerates its stems.

        Args:
            song_id: Id of the song.
            kind: Kind of asset.
            stored: Metadata returned by the storage backend.

        Returns:
            The created or updated asset.
        """
        asset = await self.get(song_id, kind)
        if asset is None:
            return await self.add(song_id, kind, stored)
        asset.storage_key = stored.key
        asset.content_type = stored.content_type
        asset.size_bytes = stored.size_bytes
        await self._session.flush()
        return asset

    async def get(self, song_id: uuid.UUID, kind: AssetKind) -> SongAsset | None:
        """Fetch the asset of a given kind for a song.

        Args:
            song_id: Id of the song.
            kind: Kind of asset.

        Returns:
            The asset, or None if the song has no asset of that kind.
        """
        return await self._session.scalar(
            select(SongAsset).where(
                SongAsset.song_id == song_id, SongAsset.kind == kind
            )
        )
