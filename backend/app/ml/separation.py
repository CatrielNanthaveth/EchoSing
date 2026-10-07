"""Source separation: split a song into vocals and accompaniment."""

import json
import sys
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from app.ml.tools import ToolError, run_tool


class SeparationError(Exception):
    """The separator failed or did not produce the expected stems."""


class SeparatedStems(BaseModel):
    """Local files produced by a separator.

    Attributes:
        vocals: Isolated lead vocals.
        accompaniment: Everything except the vocals (the karaoke track).
    """

    vocals: Path
    accompaniment: Path


class SourceSeparator(Protocol):
    """Splits a song into vocals and accompaniment."""

    @property
    def name(self) -> str:
        """Identifier of the model, recorded in the analysis metadata."""
        ...

    async def separate(self, audio: Path, output_dir: Path) -> SeparatedStems:
        """Separate a song.

        Args:
            audio: Input audio file.
            output_dir: Empty directory where stems may be written.

        Returns:
            Paths of the produced stems, inside ``output_dir``.

        Raises:
            SeparationError: If separation fails.
        """
        ...


class DemucsSeparator:
    """``SourceSeparator`` running the Demucs CLI in a subprocess.

    A separate process guarantees that all GPU memory is released when it ends
    and that a crash cannot take the worker down. Stems are written as FLAC.
    """

    def __init__(
        self,
        model: str = "htdemucs",
        device: str = "cuda",
        timeout_s: float = 900.0,
        shifts: int = 1,
        python: str = sys.executable,
    ) -> None:
        """Initialize the separator.

        Args:
            model: Pretrained Demucs model name.
            device: Torch device (``cuda`` or ``cpu``).
            timeout_s: Max seconds for one separation.
            shifts: Random shifts averaged to reduce artifacts (time x shifts).
            python: Python interpreter with Demucs installed.
        """
        self._model = model
        self._device = device
        self._shifts = shifts
        self._timeout_s = timeout_s
        self._python = python

    @property
    def name(self) -> str:
        """Identifier of the configuration, e.g. ``htdemucs(shifts=5)``."""
        return f"{self._model}(shifts={self._shifts})"

    def command(self, audio: Path, output_dir: Path) -> list[str]:
        """Build the Demucs command line.

        Args:
            audio: Input audio file.
            output_dir: Output directory.

        Returns:
            The command and its arguments.
        """
        return [
            self._python,
            "-m",
            "demucs",
            "-n",
            self._model,
            "-d",
            self._device,
            "--shifts",
            str(self._shifts),
            "--two-stems",
            "vocals",
            "--flac",
            "-o",
            str(output_dir),
            "--filename",
            "{stem}.{ext}",
            str(audio),
        ]

    async def separate(self, audio: Path, output_dir: Path) -> SeparatedStems:
        """Run Demucs. See ``SourceSeparator``."""
        try:
            await run_tool(self.command(audio, output_dir), timeout_s=self._timeout_s)
        except ToolError as error:
            raise SeparationError(f"Demucs failed: {error}") from error

        # Demucs writes into a sub-folder named after the model.
        stems_dir = output_dir / self._model
        stems = SeparatedStems(
            vocals=stems_dir / "vocals.flac",
            accompaniment=stems_dir / "no_vocals.flac",
        )
        for path in (stems.vocals, stems.accompaniment):
            if not path.is_file():
                raise SeparationError(f"Demucs did not produce {path.name}")
        return stems


class RoformerSeparator:
    """``SourceSeparator`` running a RoFormer model through ``audio-separator``.

    Like ``DemucsSeparator``, it runs in a subprocess so all GPU memory is
    released afterwards. audio-separator uses CUDA automatically when available.
    """

    def __init__(
        self,
        model: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        models_dir: Path = Path("models"),
        normalization: float = 0.9,
        timeout_s: float = 900.0,
        python: str = sys.executable,
    ) -> None:
        """Initialize the separator.

        Args:
            model: audio-separator model file name.
            models_dir: Directory where model weights are downloaded and cached.
            normalization: Peak amplitude input and output are normalized to.
            timeout_s: Max seconds for one separation.
            python: Python interpreter with audio-separator installed.
        """
        self._model = model
        self._models_dir = models_dir
        self._normalization = normalization
        self._timeout_s = timeout_s
        self._python = python

    @property
    def name(self) -> str:
        """Identifier of the model, without the weights file extension."""
        return Path(self._model).stem

    def command(self, audio: Path, output_dir: Path) -> list[str]:
        """Build the audio-separator command line.

        Args:
            audio: Input audio file.
            output_dir: Output directory.

        Returns:
            The command and its arguments.
        """
        return [
            self._python,
            "-c",
            "from audio_separator.utils.cli import main; main()",
            str(audio),
            "--model_filename",
            self._model,
            "--model_file_dir",
            str(self._models_dir),
            "--output_dir",
            str(output_dir),
            "--output_format",
            "FLAC",
            "--normalization",
            str(self._normalization),
            "--custom_output_names",
            json.dumps({"Vocals": "vocals", "Instrumental": "instrumental"}),
            "--log_level",
            "warning",
        ]

    async def separate(self, audio: Path, output_dir: Path) -> SeparatedStems:
        """Run audio-separator. See ``SourceSeparator``."""
        try:
            await run_tool(self.command(audio, output_dir), timeout_s=self._timeout_s)
        except ToolError as error:
            raise SeparationError(f"audio-separator failed: {error}") from error

        stems = SeparatedStems(
            vocals=output_dir / "vocals.flac",
            accompaniment=output_dir / "instrumental.flac",
        )
        for path in (stems.vocals, stems.accompaniment):
            if not path.is_file():
                raise SeparationError(f"audio-separator did not produce {path.name}")
        return stems
