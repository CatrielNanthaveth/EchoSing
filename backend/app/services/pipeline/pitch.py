"""Ingestion stage: reference pitch of the isolated vocals.

Also cross-checks the transcription against the pitch: words sung over no
voice are likely hallucinations (layer B of the hallucination filter). They
are reported and, when enabled, moved to the transcription's ``discarded``.
"""

import tempfile
import uuid
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.song_assets import SongAssetRepository
from app.db.repositories.songs import SongRepository
from app.domain.enums import AssetKind
from app.ml.pitch import CrepeExtractor, PitchExtractor
from app.ml.transcription import TranscribedWord
from app.schemas.analysis import PitchCurve
from app.services.pipeline.errors import StageError
from app.services.pipeline.segmentation import load_lines
from app.services.pipeline.transcription import (
    TRANSCRIPTION_ARTIFACT,
    load_transcription,
)
from app.services.voicing import LinePitchStats, find_unvoiced_words, line_pitch_stats
from app.storage.base import ObjectNotFoundError, StorageBackend
from app.storage.keys import work_key

PITCH_ARTIFACT = "pitch.json"


class PitchResult(BaseModel):
    """Outcome of the pitch stage.

    Attributes:
        song_id: Id of the processed song.
        artifact_key: Storage key of the saved pitch curve.
        extractor: Model configuration that produced the curve.
        frame_count: Number of frames in the curve.
        voiced_ratio: Fraction of frames sung with enough confidence.
        unvoiced_words: Words of phrases transcribed over no voice.
        unvoiced_words_discarded: Whether such words are removed from the
            transcription (the filter is enabled) or only reported.
        line_stats: Pitch summary per lyric line, if lines were built.
    """

    song_id: uuid.UUID
    artifact_key: str
    extractor: str
    frame_count: int
    voiced_ratio: float
    unvoiced_words: list[TranscribedWord]
    unvoiced_words_discarded: bool
    line_stats: list[LinePitchStats]


async def load_pitch(storage: StorageBackend, song_id: uuid.UUID) -> PitchCurve:
    """Read the pitch curve saved by this stage.

    Args:
        storage: Storage backend.
        song_id: Id of the song.

    Returns:
        The saved curve.

    Raises:
        app.storage.base.ObjectNotFoundError: If the stage has not run yet.
    """
    key = work_key(song_id, PITCH_ARTIFACT)
    content = b"".join([chunk async for chunk in await storage.stream(key)])
    return PitchCurve.model_validate_json(content)


class PitchStage:
    """Extracts and saves the reference pitch of a song's vocals."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        extractor: PitchExtractor,
        *,
        min_confidence: int = 50,
        max_voiced_ratio: float = 0.05,
        min_run_words: int = 3,
        discard_unvoiced_words: bool = True,
    ) -> None:
        """Initialize the stage.

        Args:
            session: Database session, used to find the vocals asset.
            storage: Storage holding the vocals and receiving the curve.
            extractor: Pitch extraction model.
            min_confidence: Confidence (0-100) from which a frame counts as
                sung.
            max_voiced_ratio: Words with a lower fraction of sung frames count
                as unvoiced.
            min_run_words: Consecutive unvoiced words that form a hallucinated
                phrase.
            discard_unvoiced_words: Whether hallucinated phrases are removed
                from the transcription (otherwise they are only reported).
        """
        self._songs = SongRepository(session)
        self._assets = SongAssetRepository(session)
        self._storage = storage
        self._extractor = extractor
        self._min_confidence = min_confidence
        self._max_voiced_ratio = max_voiced_ratio
        self._min_run_words = min_run_words
        self._discard_unvoiced_words = discard_unvoiced_words

    async def run(self, song_id: uuid.UUID) -> PitchResult:
        """Extract the pitch of a song and check its transcription against it.

        Args:
            song_id: Id of the song.

        Returns:
            The curve summary, hallucination candidates and per-line stats.

        Raises:
            StageError: If the song or its vocals are missing.
            app.ml.pitch.PitchExtractionError: If extraction fails.
        """
        if await self._songs.get(song_id) is None:
            raise StageError(f"Song {song_id} does not exist")
        vocals = await self._assets.get(song_id, AssetKind.VOCALS)
        if vocals is None:
            raise StageError(
                f"Song {song_id} has no vocals; run the 'separate' stage first"
            )

        with tempfile.TemporaryDirectory(prefix="echosing-pitch-") as tmp:
            async with self._storage.local_path(vocals.storage_key) as audio:
                curve = await self._extractor.extract(audio, Path(tmp))

        key = work_key(song_id, PITCH_ARTIFACT)
        await self._storage.save(
            key, curve.model_dump_json().encode(), "application/json"
        )

        unvoiced = await self._check_transcription(song_id, curve)
        voiced_frames = int(
            np.count_nonzero(np.asarray(curve.confidence) >= self._min_confidence)
        )
        return PitchResult(
            song_id=song_id,
            artifact_key=key,
            extractor=self._extractor.name,
            frame_count=curve.frame_count,
            voiced_ratio=voiced_frames / curve.frame_count
            if curve.frame_count
            else 0.0,
            unvoiced_words=unvoiced,
            unvoiced_words_discarded=self._discard_unvoiced_words,
            line_stats=await self._line_stats(song_id, curve),
        )

    async def _check_transcription(
        self, song_id: uuid.UUID, curve: PitchCurve
    ) -> list[TranscribedWord]:
        """Report (and optionally discard) words sung over no voice."""
        try:
            transcription = await load_transcription(self._storage, song_id)
        except ObjectNotFoundError:
            return []
        suspicious = set(
            find_unvoiced_words(
                transcription.words,
                curve,
                min_confidence=self._min_confidence,
                max_voiced_ratio=self._max_voiced_ratio,
                min_run_words=self._min_run_words,
            )
        )
        unvoiced = [w for i, w in enumerate(transcription.words) if i in suspicious]
        if self._discard_unvoiced_words and unvoiced:
            cleaned = transcription.model_copy(
                update={
                    "words": [
                        w
                        for i, w in enumerate(transcription.words)
                        if i not in suspicious
                    ],
                    "discarded": sorted(
                        [*transcription.discarded, *unvoiced],
                        key=lambda word: word.start_ms,
                    ),
                }
            )
            await self._storage.save(
                work_key(song_id, TRANSCRIPTION_ARTIFACT),
                cleaned.model_dump_json(indent=2).encode(),
                "application/json",
            )
        return unvoiced

    async def _line_stats(
        self, song_id: uuid.UUID, curve: PitchCurve
    ) -> list[LinePitchStats]:
        """Summarize the pitch of each lyric line, if lines were built."""
        try:
            lyrics = await load_lines(self._storage, song_id)
        except ObjectNotFoundError:
            return []
        return line_pitch_stats(lyrics.lines, curve, self._min_confidence)


def build_pitch_stage(
    session: AsyncSession, storage: StorageBackend, settings: Settings
) -> PitchStage:
    """Create a pitch stage using torchcrepe as configured in the settings.

    Args:
        session: Database session.
        storage: Storage backend.
        settings: Application settings.

    Returns:
        The configured stage.
    """
    extractor = CrepeExtractor(
        model=settings.crepe_model,
        decoder=settings.crepe_decoder,
        fmin_hz=settings.crepe_fmin_hz,
        fmax_hz=settings.crepe_fmax_hz,
        batch_size=settings.crepe_batch_size,
        device=settings.ml_device,
        timeout_s=settings.pitch_timeout_s,
    )
    return PitchStage(
        session,
        storage,
        extractor,
        min_confidence=settings.voicing_min_confidence,
        max_voiced_ratio=settings.hallucination_max_voiced_ratio,
        min_run_words=settings.hallucination_min_run_words,
        discard_unvoiced_words=settings.hallucination_voicing_filter,
    )
