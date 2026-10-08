import uuid
from pathlib import Path

from app.services.pipeline.manifest import (
    PipelineManifest,
    load_manifest,
    update_manifest,
)
from app.storage.local import LocalStorage

SONG_ID = uuid.UUID("0e0b2cdf-45cb-48b0-8b06-e558286f0c18")


async def test_missing_manifest_is_empty(tmp_path: Path) -> None:
    assert await load_manifest(LocalStorage(tmp_path), SONG_ID) == PipelineManifest()


async def test_updates_accumulate_and_keep_other_stages(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    await update_manifest(storage, SONG_ID, separator="htdemucs(shifts=5)")
    await update_manifest(storage, SONG_ID, transcriber="whisper-large-v3-turbo")
    updated = await update_manifest(
        storage, SONG_ID, pitch_extractor="torchcrepe-full-viterbi"
    )

    expected = PipelineManifest(
        separator="htdemucs(shifts=5)",
        transcriber="whisper-large-v3-turbo",
        pitch_extractor="torchcrepe-full-viterbi",
    )
    assert updated == expected
    assert await load_manifest(storage, SONG_ID) == expected


async def test_rerunning_a_stage_overwrites_its_model(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await update_manifest(storage, SONG_ID, separator="htdemucs(shifts=5)")

    await update_manifest(storage, SONG_ID, separator="model_bs_roformer")

    assert (await load_manifest(storage, SONG_ID)).separator == "model_bs_roformer"
