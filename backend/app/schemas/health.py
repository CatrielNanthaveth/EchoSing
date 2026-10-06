"""Schemas for the health check endpoint."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Overall service health status.

    Attributes:
        status: ``"ok"`` when the service is able to handle requests.
    """

    status: Literal["ok"]
