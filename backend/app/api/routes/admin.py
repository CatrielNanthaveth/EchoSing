"""Admin routes for managing the song catalog."""

import uuid
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
from app.services.song_lyrics import (
    EmptyLyricsError,
    LyricsSummary,
    LyricsUpdate,
    SongLyricsService,
    SongNotFoundError,
    get_song_lyrics_service,
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
    separation_preset: Annotated[str | None, Form()] = None,
    lyrics: Annotated[str | None, Form()] = None,
) -> SongRegistration:
    """Upload a song and queue it for processing.

    ``separation_preset`` is ``demucs`` or ``roformer``; empty means the
    server default. ``lyrics`` are the official lyrics, one verse per line.
    """
    try:
        # Empty form fields mean "not provided".
        new_song = NewSong.model_validate(
            {
                "title": title,
                "artist": artist,
                "language": language or None,
                "separation_preset": separation_preset or None,
                "lyrics": lyrics or None,
            }
        )
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


@router.put(
    "/songs/{song_id}/lyrics",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_404_NOT_FOUND: {"description": "Song not found"},
    },
)
async def set_song_lyrics(
    song_id: uuid.UUID,
    body: LyricsUpdate,
    service: Annotated[SongLyricsService, Depends(get_song_lyrics_service)],
) -> LyricsSummary:
    """Set the official lyrics of a song (one verse per line).

    They are used the next time the song's lines are built.
    """
    try:
        return await service.set_lyrics(song_id, body.lyrics)
    except SongNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EmptyLyricsError as error:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "lyrics"),
                    "msg": str(error),
                    "input": body.lyrics,
                }
            ]
        ) from error
