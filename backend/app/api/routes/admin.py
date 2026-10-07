"""Admin routes for managing the song catalog."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.security import require_admin_token
from app.services.song_ingestion import (
    NewSong,
    SongIngestionService,
    SongRegistration,
    UnsupportedAudioFormatError,
    UploadTooLargeError,
    get_song_ingestion_service,
)
from app.storage.base import CHUNK_SIZE
from app.workers.queue import QueueUnavailableError

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


async def _read_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """Yield the content of an uploaded file in chunks."""
    while chunk := await upload.read(CHUNK_SIZE):
        yield chunk


@router.post(
    "/songs",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_413_CONTENT_TOO_LARGE: {"description": "File too large"},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "Not an audio file"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Queue or admin down"},
    },
)
async def upload_song(
    file: UploadFile,
    title: Annotated[str, Form()],
    artist: Annotated[str, Form()],
    service: Annotated[SongIngestionService, Depends(get_song_ingestion_service)],
    language: Annotated[str | None, Form()] = None,
) -> SongRegistration:
    """Upload a song and queue it for processing."""
    try:
        new_song = NewSong(title=title, artist=artist, language=language or None)
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error

    try:
        return await service.register_song(
            new_song, file.filename or "", _read_chunks(file)
        )
    except UnsupportedAudioFormatError as error:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(error)
        ) from error
    except UploadTooLargeError as error:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)
        ) from error
    except QueueUnavailableError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The song was stored but could not be queued; it is marked failed",
        ) from error
