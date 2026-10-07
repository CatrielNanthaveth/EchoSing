"""Storage abstraction for audio files and other binary objects."""

import re
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

CHUNK_SIZE = 64 * 1024
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


class StorageError(Exception):
    """Base class for storage errors."""


class InvalidKeyError(StorageError):
    """The key is malformed or tries to escape the storage root."""


class ObjectNotFoundError(StorageError):
    """No object is stored under the requested key."""


class InvalidRangeError(StorageError):
    """The requested byte range does not fit inside the object."""


class StoredObject(BaseModel):
    """Metadata of an object that was written to storage.

    Attributes:
        key: Storage key of the object.
        size_bytes: Size of the stored content.
        content_type: MIME type declared when saving.
    """

    key: str
    size_bytes: int
    content_type: str


def validate_key(key: str) -> str:
    """Check that ``key`` is a safe, relative, slash-separated object key.

    Args:
        key: Key such as ``songs/<id>/original.mp3``.

    Returns:
        The same key, if valid.

    Raises:
        InvalidKeyError: If the key is empty, absolute, uses backslashes or a
            drive letter, contains NUL, or has empty, ``.`` or ``..`` segments.
    """
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or _DRIVE_LETTER.match(key)
        or any(part in ("", ".", "..") for part in key.split("/"))
    ):
        raise InvalidKeyError(f"Invalid storage key: {key!r}")
    return key


def validate_prefix(prefix: str) -> str:
    """Check that ``prefix`` is a valid key followed by a trailing slash.

    Args:
        prefix: Prefix such as ``songs/<id>/``.

    Returns:
        The same prefix, if valid.

    Raises:
        InvalidKeyError: If the prefix lacks the trailing slash or is invalid.
    """
    if not prefix.endswith("/"):
        raise InvalidKeyError(f"Storage prefix must end with '/': {prefix!r}")
    validate_key(prefix[:-1])
    return prefix


class StorageBackend(Protocol):
    """Object storage used for uploaded songs and generated stems.

    Keys are relative, slash-separated paths (see ``validate_key``). Writes are
    atomic: a failed write never leaves a partial object behind.
    """

    async def save(
        self, key: str, data: bytes | AsyncIterable[bytes], content_type: str
    ) -> StoredObject:
        """Store content under ``key``, replacing any previous object.

        Args:
            key: Destination key.
            data: Whole content, or an async stream of chunks.
            content_type: MIME type of the content.

        Returns:
            Metadata of the stored object.
        """
        ...

    async def save_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        """Store a copy of a local file under ``key``.

        Args:
            key: Destination key.
            path: File to copy (e.g. a stem written by an ML tool).
            content_type: MIME type of the content.

        Returns:
            Metadata of the stored object.
        """
        ...

    async def stream(
        self, key: str, start: int = 0, stop: int | None = None
    ) -> AsyncIterator[bytes]:
        """Open a chunked reader over the bytes ``[start, stop)`` of an object.

        The key and range are validated before this coroutine returns, so
        errors surface before any byte is sent to a client.

        Args:
            key: Key of the object.
            start: First byte offset (inclusive).
            stop: End offset (exclusive); defaults to the object size.

        Returns:
            An async iterator of chunks.
        """
        ...

    def local_path(self, key: str) -> AbstractAsyncContextManager[Path]:
        """Expose an object as a local file for tools that need a real path.

        Args:
            key: Key of the object.

        Returns:
            A context manager yielding a readable path, valid inside the block.
        """
        ...

    async def size(self, key: str) -> int:
        """Return the size in bytes of an object."""
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object is stored under ``key``."""
        ...

    async def delete(self, key: str) -> None:
        """Delete an object; deleting a missing object is a no-op."""
        ...

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every object under ``prefix`` (which must end with ``/``)."""
        ...
