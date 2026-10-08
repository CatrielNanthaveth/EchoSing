"""Public catalog routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.catalog import SongDetail, SongPage
from app.services.catalog import CatalogService, get_catalog_service
from app.services.errors import SongNotFoundError

router = APIRouter(prefix="/songs", tags=["catalog"])


@router.get("")
async def list_songs(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SongPage:
    """List the playable songs, searching title and artist with ``q``."""
    return await service.list_songs(q or None, limit, offset)


@router.get(
    "/{song_id}",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Song not available"}},
)
async def get_song(
    song_id: uuid.UUID,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> SongDetail:
    """Get a playable song with its synced lyrics (without the pitch curve)."""
    try:
        return await service.get_song(song_id)
    except SongNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
