"""Public catalog routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.http_range import RangeNotSatisfiableError, parse_range
from app.schemas.catalog import PitchResponse, SongDetail, SongPage
from app.services.catalog import (
    CatalogService,
    LineNotFoundError,
    get_catalog_service,
)
from app.services.errors import SongNotFoundError
from app.storage.base import StorageBackend
from app.storage.dependencies import get_storage

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


@router.get(
    "/{song_id}/instrumental",
    response_class=StreamingResponse,
    responses={
        status.HTTP_206_PARTIAL_CONTENT: {"description": "Requested byte range"},
        status.HTTP_404_NOT_FOUND: {"description": "Song not available"},
        status.HTTP_416_RANGE_NOT_SATISFIABLE: {"description": "Range out of file"},
    },
)
async def stream_instrumental(
    song_id: uuid.UUID,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Stream the karaoke track, supporting HTTP range requests (seeking)."""
    try:
        audio = await service.get_instrumental(song_id)
    except SongNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    size = await storage.size(audio.storage_key)
    headers = {"Accept-Ranges": "bytes"}
    try:
        byte_range = parse_range(range_header, size)
    except RangeNotSatisfiableError:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**headers, "Content-Range": f"bytes */{size}"},
        )

    start, stop = (
        (0, size) if byte_range is None else (byte_range.start, byte_range.stop)
    )
    headers["Content-Length"] = str(stop - start)
    if byte_range is not None:
        headers["Content-Range"] = byte_range.content_range(size)
    return StreamingResponse(
        await storage.stream(audio.storage_key, start, stop),
        status_code=(
            status.HTTP_200_OK
            if byte_range is None
            else status.HTTP_206_PARTIAL_CONTENT
        ),
        media_type=audio.content_type,
        headers=headers,
    )


@router.get(
    "/{song_id}/pitch",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Song or line not found"}},
)
async def get_pitch(
    song_id: uuid.UUID,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    line: Annotated[int | None, Query(ge=0)] = None,
) -> PitchResponse:
    """Get the reference pitch of a song, or of one line with ``line``."""
    try:
        return await service.get_pitch(song_id, line)
    except (SongNotFoundError, LineNotFoundError) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
