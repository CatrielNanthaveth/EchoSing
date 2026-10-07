"""FastAPI dependency providing the configured storage backend."""

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorage


def get_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StorageBackend:
    """Provide the storage backend configured in the settings.

    Args:
        settings: Application settings.

    Returns:
        A ``LocalStorage`` rooted at ``settings.storage_root``.
    """
    return LocalStorage(settings.storage_root)
