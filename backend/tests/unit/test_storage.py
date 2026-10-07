import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.enums import AssetKind
from app.storage.base import (
    CHUNK_SIZE,
    InvalidKeyError,
    InvalidRangeError,
    ObjectNotFoundError,
    StorageBackend,
    validate_prefix,
)
from app.storage.dependencies import get_storage
from app.storage.keys import asset_key, song_prefix
from app.storage.local import LocalStorage

KEY = "songs/abc/original.mp3"
CONTENT = bytes(range(256)) * 1024  # 256 KiB, spans several chunks


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def storage(root: Path) -> LocalStorage:
    return LocalStorage(root)


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def _read_all(storage: StorageBackend, key: str, **kwargs: int) -> bytes:
    return b"".join([chunk async for chunk in await storage.stream(key, **kwargs)])


def _all_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


# --- save --------------------------------------------------------------------


async def test_save_bytes(storage: LocalStorage) -> None:
    stored = await storage.save(KEY, CONTENT, "audio/mpeg")

    assert stored.key == KEY
    assert stored.size_bytes == len(CONTENT)
    assert stored.content_type == "audio/mpeg"
    assert await _read_all(storage, KEY) == CONTENT


async def test_save_async_chunks(storage: LocalStorage) -> None:
    stored = await storage.save(KEY, _chunks(b"abc", b"", b"defg"), "audio/mpeg")

    assert stored.size_bytes == 7
    assert await _read_all(storage, KEY) == b"abcdefg"


async def test_save_replaces_existing_object(storage: LocalStorage) -> None:
    await storage.save(KEY, b"old content", "audio/mpeg")
    await storage.save(KEY, b"new", "audio/mpeg")

    assert await _read_all(storage, KEY) == b"new"


async def test_failed_stream_leaves_no_object(
    storage: LocalStorage, root: Path
) -> None:
    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise ConnectionError("client disconnected")

    with pytest.raises(ConnectionError):
        await storage.save(KEY, broken(), "audio/mpeg")

    assert not await storage.exists(KEY)
    assert _all_files(root) == []


async def test_failed_stream_keeps_previous_object(storage: LocalStorage) -> None:
    await storage.save(KEY, b"original", "audio/mpeg")

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise ConnectionError("client disconnected")

    with pytest.raises(ConnectionError):
        await storage.save(KEY, broken(), "audio/mpeg")

    assert await _read_all(storage, KEY) == b"original"


# --- save_file ---------------------------------------------------------------


async def test_save_file_copies_local_file(
    storage: LocalStorage, tmp_path: Path
) -> None:
    source = tmp_path / "vocals.wav"
    source.write_bytes(CONTENT)

    stored = await storage.save_file("songs/abc/vocals.wav", source, "audio/wav")

    assert stored.size_bytes == len(CONTENT)
    assert await _read_all(storage, "songs/abc/vocals.wav") == CONTENT
    assert source.exists()


async def test_save_file_missing_source(storage: LocalStorage, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await storage.save_file(KEY, tmp_path / "missing.wav", "audio/wav")


async def test_save_file_failure_leaves_no_temporary(
    storage: LocalStorage, root: Path, tmp_path: Path
) -> None:
    source = tmp_path / "stem.wav"
    source.write_bytes(b"data")
    await storage.save("songs/abc/stem.wav/inner", b"x", "text/plain")

    # The copy to the temporary file succeeds, but the final rename fails
    # because a directory already occupies the destination path.
    with pytest.raises(OSError):
        await storage.save_file("songs/abc/stem.wav", source, "audio/wav")

    assert _all_files(root) == [root / "songs" / "abc" / "stem.wav" / "inner"]


async def test_stream_stops_if_object_is_truncated_while_reading(
    storage: LocalStorage, root: Path
) -> None:
    await storage.save(KEY, CONTENT, "audio/mpeg")
    iterator = await storage.stream(KEY)

    (root / KEY).write_bytes(b"short")

    assert b"".join([chunk async for chunk in iterator]) == b"short"


# --- stream ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "stop"),
    [
        (0, None),
        (0, len(CONTENT)),
        (1000, CHUNK_SIZE + 5000),
        (len(CONTENT) - 1, None),
        (10, 10),
    ],
)
async def test_stream_ranges(
    storage: LocalStorage, start: int, stop: int | None
) -> None:
    await storage.save(KEY, CONTENT, "audio/mpeg")

    chunks = [chunk async for chunk in await storage.stream(KEY, start, stop)]

    assert b"".join(chunks) == CONTENT[start:stop]
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)


@pytest.mark.parametrize(("start", "stop"), [(-1, None), (5, 4), (0, len(CONTENT) + 1)])
async def test_stream_invalid_range(
    storage: LocalStorage, start: int, stop: int | None
) -> None:
    await storage.save(KEY, CONTENT, "audio/mpeg")

    with pytest.raises(InvalidRangeError):
        await storage.stream(KEY, start, stop)


async def test_stream_missing_object_fails_before_iteration(
    storage: LocalStorage,
) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.stream(KEY)


# --- metadata, local_path and deletion --------------------------------------


async def test_size_and_exists(storage: LocalStorage) -> None:
    assert not await storage.exists(KEY)
    with pytest.raises(ObjectNotFoundError):
        await storage.size(KEY)

    await storage.save(KEY, b"12345", "audio/mpeg")

    assert await storage.exists(KEY)
    assert await storage.size(KEY) == 5


async def test_local_path_yields_existing_file(storage: LocalStorage) -> None:
    await storage.save(KEY, b"audio", "audio/mpeg")

    async with storage.local_path(KEY) as path:
        assert path.read_bytes() == b"audio"


async def test_local_path_missing_object(storage: LocalStorage) -> None:
    with pytest.raises(ObjectNotFoundError):
        async with storage.local_path(KEY):
            pass


async def test_delete_is_idempotent(storage: LocalStorage) -> None:
    await storage.save(KEY, b"x", "audio/mpeg")

    await storage.delete(KEY)
    await storage.delete(KEY)

    assert not await storage.exists(KEY)


async def test_delete_prefix_only_removes_that_song(storage: LocalStorage) -> None:
    await storage.save("songs/a/original.mp3", b"a", "audio/mpeg")
    await storage.save("songs/a/vocals.wav", b"a", "audio/wav")
    await storage.save("songs/ab/original.mp3", b"b", "audio/mpeg")

    await storage.delete_prefix("songs/a/")
    await storage.delete_prefix("songs/missing/")

    assert not await storage.exists("songs/a/original.mp3")
    assert not await storage.exists("songs/a/vocals.wav")
    assert await storage.exists("songs/ab/original.mp3")


# --- key validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/abs/path.mp3",
        "../outside.mp3",
        "songs/../../outside.mp3",
        "songs/./a.mp3",
        "songs//a.mp3",
        "songs/a/",
        "C:/Windows/a.mp3",
        "c:relative.mp3",
        "songs\\a.mp3",
        "songs/a\x00.mp3",
    ],
)
async def test_invalid_keys_are_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidKeyError):
        await storage.save(key, b"x", "audio/mpeg")


@pytest.mark.parametrize("prefix", ["songs/a", "", "/", "../", "songs/../"])
def test_invalid_prefixes_are_rejected(prefix: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_prefix(prefix)


async def test_symlink_escaping_root_is_rejected(
    storage: LocalStorage, root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires extra privileges on this system")

    with pytest.raises(InvalidKeyError):
        await storage.save("link/evil.mp3", b"x", "audio/mpeg")


# --- keys and dependency -----------------------------------------------------


def test_asset_key_convention() -> None:
    song_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    assert song_prefix(song_id) == f"songs/{song_id}/"
    assert asset_key(song_id, AssetKind.VOCALS, ".WAV") == f"songs/{song_id}/vocals.wav"
    assert asset_key(song_id, AssetKind.ORIGINAL, "mp3").endswith("/original.mp3")


@pytest.mark.parametrize("extension", ["", ".", "mp3/../x", "m p3", "toolongextension"])
def test_asset_key_rejects_bad_extensions(extension: str) -> None:
    with pytest.raises(InvalidKeyError):
        asset_key(uuid.uuid4(), AssetKind.ORIGINAL, extension)


async def test_get_storage_uses_configured_root(tmp_path: Path) -> None:
    storage = get_storage(Settings(_env_file=None, storage_root=tmp_path))

    await storage.save(KEY, b"x", "audio/mpeg")

    assert (tmp_path / "songs" / "abc" / "original.mp3").read_bytes() == b"x"
