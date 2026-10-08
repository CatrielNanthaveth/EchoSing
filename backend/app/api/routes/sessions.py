"""Play session routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.sessions import SessionCreate, SessionCreated
from app.services.errors import SongNotFoundError
from app.services.play_sessions import PlaySessionService, get_play_session_service

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Song not available"}},
)
async def create_session(
    body: SessionCreate,
    service: Annotated[PlaySessionService, Depends(get_play_session_service)],
) -> SessionCreated:
    """Start singing a song; scoring is bound to its current analysis."""
    try:
        return await service.create(body)
    except SongNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
