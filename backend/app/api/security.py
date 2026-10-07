"""Access control for API routes."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def require_admin_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Allow the request only if it carries the configured admin token.

    Args:
        settings: Application settings holding the expected token.
        x_admin_token: Value of the ``X-Admin-Token`` request header.

    Raises:
        HTTPException: 503 if no admin token is configured (admin endpoints are
            disabled), 401 if the header is missing or wrong.
    """
    if settings.admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled: ECHOSING_ADMIN_TOKEN is not set",
        )
    expected = settings.admin_token.get_secret_value().encode()
    provided = (x_admin_token or "").encode()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Token header",
        )
