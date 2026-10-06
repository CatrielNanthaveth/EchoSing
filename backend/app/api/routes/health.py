"""Health check routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.schemas.health import HealthResponse
from app.services.health_service import HealthService, get_health_service

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    """Return the health status of the service."""
    return await service.check()
