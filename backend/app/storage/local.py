"""Storage backend on the local filesystem."""

import shutil
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import anyio
import anyio.to_thread

from app.storage.base import (
    CHUNK_SIZE,
    InvalidKeyError,
    InvalidRangeError,
    ObjectNotFoundError,
    StoredObject,
    validate_key,
    validate_prefix,
)


class LocalStorage:
    """``StorageBackend`` that keeps objects as files under a root directory.

    Writes go to a temporary file in the destination directory and are moved
    into place with an atomic rename once complete.
    """

    def __init__(self, root: Path) -> None:
        """Initialize the backend.

        Args:
            root: Directory holding every object; created on first write.
        """
        self._root = root.resolve()

    async def save(
        self, key: str, data: bytes | AsyncIterable[bytes], content_type: str
    ) -> StoredObject:
        """Store content under ``key`` atomically. See ``StorageBackend``."""
        destination = self._path(key)
        size = 0
        async with self._atomic_writer(destination) as file:
            if isinstance(data, bytes):
                await file.write(data)
                size = len(data)
            else:
                async for chunk in data:
                    await file.write(chunk)
                    size += len(chunk)
        return StoredObject(key=key, size_bytes=size, content_type=content_type)

    async def save_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        """Store a copy of a local file atomically. See ``StorageBackend``."""
        destination = self._path(key)
        if not await anyio.Path(path).is_file():
            raise FileNotFoundError(path)
        await anyio.Path(destination.parent).mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_path(destination)
        try:
            await anyio.to_thread.run_sync(shutil.copyfile, path, temporary)
            await anyio.Path(temporary).replace(destination)
        except BaseException:
            await anyio.Path(temporary).unlink(missing_ok=True)
            raise
        size = (await anyio.Path(destination).stat()).st_size
        return StoredObject(key=key, size_bytes=size, content_type=content_type)

    async def stream(
        self, key: str, start: int = 0, stop: int | None = None
    ) -> AsyncIterator[bytes]:
        """Open a chunked reader over ``[start, stop)``. See ``StorageBackend``."""
        path = self._path(key)
        size = await self._existing_size(key, path)
        end = size if stop is None else stop
        if not 0 <= start <= end <= size:
            raise InvalidRangeError(
                f"Range [{start}, {end}) is outside object {key!r} of {size} bytes"
            )
        return self._read_range(path, start, end)

    def local_path(self, key: str) -> AbstractAsyncContextManager[Path]:
        """Yield the real path of an object. See ``StorageBackend``."""
        return self._local_path(key)

    async def size(self, key: str) -> int:
        """Return the size in bytes of an object. See ``StorageBackend``."""
        return await self._existing_size(key, self._path(key))

    async def exists(self, key: str) -> bool:
        """Return whether an object exists. See ``StorageBackend``."""
        return await anyio.Path(self._path(key)).is_file()

    async def delete(self, key: str) -> None:
        """Delete an object if present. See ``StorageBackend``."""
        await anyio.Path(self._path(key)).unlink(missing_ok=True)

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every object under ``prefix``. See ``StorageBackend``."""
        directory = self._path(validate_prefix(prefix)[:-1])
        if await anyio.Path(directory).is_dir():
            await anyio.to_thread.run_sync(shutil.rmtree, directory)

    def _path(self, key: str) -> Path:
        """Map a key to a path, refusing anything outside the root."""
        path = (self._root / validate_key(key)).resolve()
        if not path.is_relative_to(self._root) or path == self._root:
            raise InvalidKeyError(f"Storage key escapes the root: {key!r}")
        return path

    async def _existing_size(self, key: str, path: Path) -> int:
        """Return the size of ``path`` or raise ``ObjectNotFoundError``."""
        try:
            stat = await anyio.Path(path).stat()
        except FileNotFoundError as error:
            raise ObjectNotFoundError(key) from error
        return stat.st_size

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        """Return a unique temporary sibling of ``destination``."""
        return destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")

    @asynccontextmanager
    async def _atomic_writer(
        self, destination: Path
    ) -> AsyncIterator[anyio.AsyncFile[bytes]]:
        """Write to a temporary file and move it to ``destination`` on success."""
        await anyio.Path(destination.parent).mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_path(destination)
        try:
            async with await anyio.open_file(temporary, "wb") as file:
                yield file
            await anyio.Path(temporary).replace(destination)
        except BaseException:
            await anyio.Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    async def _read_range(path: Path, start: int, stop: int) -> AsyncIterator[bytes]:
        """Yield the bytes ``[start, stop)`` of ``path`` in chunks."""
        remaining = stop - start
        async with await anyio.open_file(path, "rb") as file:
            await file.seek(start)
            while remaining > 0:
                chunk = await file.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    @asynccontextmanager
    async def _local_path(self, key: str) -> AsyncIterator[Path]:
        """Yield the path of an existing object."""
        path = self._path(key)
        await self._existing_size(key, path)
        yield path
