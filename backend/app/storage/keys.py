"""Naming convention for storage keys."""

import re
import uuid

from app.domain.enums import AssetKind
from app.storage.base import InvalidKeyError

_EXTENSION = re.compile(r"^[a-z0-9]{1,10}$")


def song_prefix(song_id: uuid.UUID) -> str:
    """Return the prefix holding every object of a song.

    Args:
        song_id: Id of the song.

    Returns:
        A prefix such as ``songs/<song_id>/``.
    """
    return f"songs/{song_id}/"


def work_key(song_id: uuid.UUID, name: str) -> str:
    """Return the key of an intermediate pipeline artifact of a song.

    Intermediate artifacts (e.g. the raw transcription) are not assets: they
    are kept so later stages can be re-run without repeating GPU work.

    Args:
        song_id: Id of the song.
        name: File name, e.g. ``transcription.json``.

    Returns:
        A key such as ``songs/<song_id>/work/transcription.json``.
    """
    return f"{song_prefix(song_id)}work/{name}"


def asset_key(song_id: uuid.UUID, kind: AssetKind, extension: str) -> str:
    """Return the storage key of a song asset.

    Args:
        song_id: Id of the song.
        kind: Kind of asset.
        extension: File extension, with or without the leading dot.

    Returns:
        A key such as ``songs/<song_id>/vocals.wav``.

    Raises:
        InvalidKeyError: If the extension is not 1-10 alphanumeric characters.
    """
    normalized = extension.lower().removeprefix(".")
    if not _EXTENSION.match(normalized):
        raise InvalidKeyError(f"Invalid file extension: {extension!r}")
    return f"{song_prefix(song_id)}{kind.value}.{normalized}"
