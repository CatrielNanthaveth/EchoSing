"""Reference pitch (F0) extraction from isolated vocals."""

import sys
from pathlib import Path
from typing import Protocol, Self

import anyio
import numpy as np
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ml.audio import transcode_to_wav
from app.ml.tools import ToolError, run_tool
from app.schemas.analysis import PitchCurve
from app.scoring.pitch import hz_to_midi

__all__ = [
    "PITCH_HOP_MS",
    "PITCH_SAMPLE_RATE",
    "CrepeExtractor",
    "PitchExtractionError",
    "PitchExtractor",
    "RawPitch",
    "hz_to_midi",
]

PITCH_SAMPLE_RATE = 16_000
PITCH_HOP_MS = 10


class PitchExtractionError(Exception):
    """The pitch extractor failed or produced unreadable output."""


class RawPitch(BaseModel):
    """Output of the pitch runner.

    Attributes:
        hop_ms: Time between frames.
        frequency_hz: Pitch estimate per frame.
        confidence: Voicing confidence per frame in [0, 1].
    """

    hop_ms: int = Field(gt=0)
    frequency_hz: list[float]
    confidence: list[float]

    @model_validator(mode="after")
    def _check_frames(self) -> Self:
        if len(self.frequency_hz) != len(self.confidence):
            raise ValueError("frequency_hz and confidence must have the same length")
        confidence = np.asarray(self.confidence)
        if confidence.size and (confidence.min() < 0 or confidence.max() > 1):
            raise ValueError("confidence values must be within [0, 1]")
        return self

    def to_curve(self) -> PitchCurve:
        """Convert to the stored representation (MIDI + confidence 0-100)."""
        return PitchCurve.from_numpy(
            hz_to_midi(np.asarray(self.frequency_hz)),
            np.asarray(self.confidence),
            self.hop_ms,
        )


class PitchExtractor(Protocol):
    """Extracts the pitch curve of sung vocals."""

    @property
    def name(self) -> str:
        """Identifier of the model, recorded in the analysis metadata."""
        ...

    async def extract(self, audio: Path, work_dir: Path) -> PitchCurve:
        """Extract the pitch of an audio file.

        Args:
            audio: Isolated vocals.
            work_dir: Empty directory for intermediate files.

        Returns:
            One frame every ``PITCH_HOP_MS`` with pitch and confidence.

        Raises:
            PitchExtractionError: If extraction fails.
        """
        ...


class CrepeExtractor:
    """``PitchExtractor`` running torchcrepe in a subprocess.

    The vocals are first decoded to 16 kHz mono WAV (CREPE's input format);
    ``app.ml.runners.crepe_runner`` then writes pitch and confidence as JSON.
    """

    def __init__(
        self,
        model: str = "full",
        decoder: str = "viterbi",
        fmin_hz: float = 65.0,
        fmax_hz: float = 1100.0,
        batch_size: int = 1024,
        device: str = "cuda",
        timeout_s: float = 900.0,
        python: str = sys.executable,
    ) -> None:
        """Initialize the extractor.

        Args:
            model: torchcrepe capacity, ``full`` or ``tiny``.
            decoder: ``viterbi``, ``weighted_argmax`` or ``argmax``.
            fmin_hz: Lowest pitch considered.
            fmax_hz: Highest pitch considered.
            batch_size: Frames per inference batch.
            device: Torch device (``cuda`` or ``cpu``).
            timeout_s: Max seconds for one extraction.
            python: Python interpreter with torchcrepe installed.
        """
        self._model = model
        self._decoder = decoder
        self._fmin_hz = fmin_hz
        self._fmax_hz = fmax_hz
        self._batch_size = batch_size
        self._device = device
        self._timeout_s = timeout_s
        self._python = python

    @property
    def name(self) -> str:
        """Identifier of the configuration, e.g. ``torchcrepe-full-viterbi``."""
        return f"torchcrepe-{self._model}-{self._decoder}"

    def command(self, wav: Path, output: Path) -> list[str]:
        """Build the runner command line.

        Args:
            wav: 16 kHz mono WAV input.
            output: JSON file to write.

        Returns:
            The command and its arguments.
        """
        return [
            self._python,
            "-m",
            "app.ml.runners.crepe_runner",
            str(wav),
            str(output),
            "--hop-ms",
            str(PITCH_HOP_MS),
            "--model",
            self._model,
            "--decoder",
            self._decoder,
            "--fmin",
            str(self._fmin_hz),
            "--fmax",
            str(self._fmax_hz),
            "--batch-size",
            str(self._batch_size),
            "--device",
            self._device,
        ]

    async def extract(self, audio: Path, work_dir: Path) -> PitchCurve:
        """Run CREPE. See ``PitchExtractor``."""
        wav = work_dir / "vocals_16k.wav"
        output = work_dir / "pitch.json"
        try:
            await transcode_to_wav(audio, wav, PITCH_SAMPLE_RATE)
            await run_tool(self.command(wav, output), timeout_s=self._timeout_s)
        except ToolError as error:
            raise PitchExtractionError(f"Pitch extraction failed: {error}") from error

        output_file = anyio.Path(output)
        if not await output_file.is_file():
            raise PitchExtractionError("The pitch runner did not produce its output")
        try:
            raw = RawPitch.model_validate_json(await output_file.read_text("utf-8"))
        except ValidationError as error:
            raise PitchExtractionError("Unreadable pitch runner output") from error
        return raw.to_curve()
