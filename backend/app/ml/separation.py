"""Source separation: split a song into vocals and accompaniment."""

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
        python: str = sys.executable,
    ) -> None:
        """Initialize the separator.

        Args:
            model: Pretrained Demucs model name.
            device: Torch device (``cuda`` or ``cpu``).
            timeout_s: Max seconds for one separation.
            python: Python interpreter with Demucs installed.
        """
        self._model = model
        self._device = device
        self._timeout_s = timeout_s
        self._python = python

    @property
    def name(self) -> str:
        """Identifier of the model, e.g. ``htdemucs``."""
        return self._model

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
