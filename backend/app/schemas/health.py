"""Schemas for the health check endpoint."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["up", "down"]


class HealthResponse(BaseModel):
    """Overall service health status.

    Attributes:
        status: ``"ok"`` when every dependency is up, ``"degraded"`` otherwise.
        checks: Status of each external dependency, keyed by its name.
    """

    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]
