"""Play session routes: REST and the real-time scoring WebSocket."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.schemas.sessions import (
    ClientMessage,
    ErrorCode,
    ErrorMessage,
    FinishMessage,
    ReadyMessage,
    SessionCreate,
    SessionCreated,
    SessionResults,
    SessionSummaryMessage,
)
from app.services.errors import SongNotFoundError
from app.services.play_sessions import (
    LineAlreadyScoredError,
    PlaySessionService,
    SessionFinishedError,
    SessionNotFoundError,
    UnknownLineError,
    get_play_session_service,
)

router = APIRouter(tags=["sessions"])

_CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

# Application-defined WebSocket close codes (4000-4999).
CLOSE_SESSION_NOT_FOUND = 4404
CLOSE_SESSION_FINISHED = 4409


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


@router.get(
    "/sessions/{session_id}/results",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Session not found"}},
)
async def get_session_results(
    session_id: uuid.UUID,
    service: Annotated[PlaySessionService, Depends(get_play_session_service)],
) -> SessionResults:
    """Report a session: totals and the result of every line."""
    try:
        return await service.get_results(session_id)
    except SessionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error


async def _send(websocket: WebSocket, message: BaseModel) -> None:
    await websocket.send_text(message.model_dump_json())


@router.websocket("/ws/sessions/{session_id}")
async def session_socket(
    websocket: WebSocket,
    session_id: uuid.UUID,
    service: Annotated[PlaySessionService, Depends(get_play_session_service)],
) -> None:
    """Score each sung line in real time (protocol: docs/ws-protocol.md)."""
    await websocket.accept()
    try:
        live = await service.open(session_id)
    except SessionNotFoundError as error:
        await websocket.close(code=CLOSE_SESSION_NOT_FOUND, reason=str(error))
        return
    except SessionFinishedError as error:
        await websocket.close(code=CLOSE_SESSION_FINISHED, reason=str(error))
        return

    await _send(
        websocket,
        ReadyMessage(
            session_id=live.session_id,
            analysis_id=live.analysis_id,
            line_count=len(live.lines),
            scored_lines=sorted(live.results),
        ),
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = _CLIENT_MESSAGE.validate_json(raw)
            except ValidationError as error:
                await _send(
                    websocket,
                    ErrorMessage(
                        code=ErrorCode.INVALID_MESSAGE,
                        detail=str(error.errors(include_url=False)[:3]),
                    ),
                )
                continue
            if isinstance(message, FinishMessage):
                totals = await service.finish(live)
                await _send(
                    websocket, SessionSummaryMessage.model_validate(totals.model_dump())
                )
                await websocket.close()
                return
            try:
                await _send(websocket, await service.score_line(live, message))
            except UnknownLineError as error:
                await _send(
                    websocket,
                    ErrorMessage(code=ErrorCode.UNKNOWN_LINE, detail=str(error)),
                )
            except LineAlreadyScoredError as error:
                await _send(
                    websocket,
                    ErrorMessage(code=ErrorCode.LINE_ALREADY_SCORED, detail=str(error)),
                )
    except WebSocketDisconnect:
        return
