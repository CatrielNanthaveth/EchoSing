"""Record of the models that produced a song's pipeline artifacts.

Each stage writes the identifier of its model, so the final analysis can state
how it was produced even when stages run separately (e.g. from the CLI).
"""

import uuid

from pydantic import BaseModel

from app.storage.base import ObjectNotFoundError, StorageBackend
from app.storage.keys import work_key

MANIFEST_ARTIFACT = "manifest.json"


class PipelineManifest(BaseModel):
    """Models used by the stages that ran for a song.

    Attributes:
        separator: Source separation model.
        transcriber: Speech recognition model.
        pitch_extractor: Pitch extraction model.
    """

    separator: str | None = None
    transcriber: str | None = None
    pitch_extractor: str | None = None


async def load_manifest(
    storage: StorageBackend, song_id: uuid.UUID
) -> PipelineManifest:
    """Read a song's manifest.

    Args:
        storage: Storage backend.
        song_id: Id of the song.

    Returns:
        The manifest; empty if no stage has recorded anything yet.
    """
    key = work_key(song_id, MANIFEST_ARTIFACT)
    try:
        content = b"".join([chunk async for chunk in await storage.stream(key)])
    except ObjectNotFoundError:
        return PipelineManifest()
    return PipelineManifest.model_validate_json(content)


async def update_manifest(
    storage: StorageBackend,
    song_id: uuid.UUID,
    *,
    separator: str | None = None,
    transcriber: str | None = None,
    pitch_extractor: str | None = None,
) -> PipelineManifest:
    """Record the model of one or more stages, keeping the others.

    Args:
        storage: Storage backend.
        song_id: Id of the song.
        separator: Source separation model, if it just ran.
        transcriber: Speech recognition model, if it just ran.
        pitch_extractor: Pitch extraction model, if it just ran.

    Returns:
        The updated manifest.
    """
    current = await load_manifest(storage, song_id)
    changes = {
        name: value
        for name, value in (
            ("separator", separator),
            ("transcriber", transcriber),
            ("pitch_extractor", pitch_extractor),
        )
        if value is not None
    }
    updated = current.model_copy(update=changes)
    await storage.save(
        work_key(song_id, MANIFEST_ARTIFACT),
        updated.model_dump_json(indent=2).encode(),
        "application/json",
    )
    return updated
