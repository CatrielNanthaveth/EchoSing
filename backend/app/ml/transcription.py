"""Speech recognition with word-level timestamps on isolated vocals."""

import json
import sys
import unicodedata
from pathlib import Path
from typing import Protocol

import anyio
from pydantic import BaseModel, Field, ValidationError

from app.ml.tools import ToolError, run_tool

MIN_WORD_MS = 10
HALLUCINATION_MIN_GAP_MS = 3000

# Phrases Whisper is known to invent over silence or music (learned from video
# subtitles). Matching ignores case, accents and punctuation.
KNOWN_HALLUCINATIONS = (
    "gracias por ver el video",
    "gracias por ver",
    "subtítulos realizados por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "amara.org",
    "suscríbete al canal",
    "no olvides suscribirte",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
)


class TranscriptionError(Exception):
    """The transcriber failed or produced unreadable output."""


class TranscribedWord(BaseModel):
    """A recognized word with its timing.

    Attributes:
        text: The word, including attached punctuation, without surrounding
            whitespace.
        start_ms: Start time from the beginning of the song.
        end_ms: End time, always greater than ``start_ms``.
        probability: Recognition confidence in [0, 1], if available.
    """

    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int
    probability: float | None = Field(default=None, ge=0.0, le=1.0)


class Transcription(BaseModel):
    """Result of transcribing a song's vocals.

    Attributes:
        model: Model that produced the transcription.
        language: Language used or detected, if known.
        words: Recognized words, sorted and non-overlapping.
        discarded: Words removed as known hallucinations, kept for review.
    """

    model: str
    language: str | None
    words: list[TranscribedWord]
    discarded: list[TranscribedWord] = []

    @property
    def text(self) -> str:
        """The words joined by spaces."""
        return " ".join(word.text for word in self.words)


class Transcriber(Protocol):
    """Transcribes sung vocals into timed words."""

    @property
    def name(self) -> str:
        """Identifier of the model, recorded in the analysis metadata."""
        ...

    async def transcribe(
        self, audio: Path, output_dir: Path, language: str | None
    ) -> Transcription:
        """Transcribe an audio file.

        Args:
            audio: Isolated vocals.
            output_dir: Empty directory where intermediate files may be written.
            language: ISO 639-1 code to force, or None to auto-detect.

        Returns:
            The transcription.

        Raises:
            TranscriptionError: If transcription fails.
        """
        ...


class _WhisperWord(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class _WhisperSegment(BaseModel):
    start: float = 0.0
    words: list[_WhisperWord] = []


class _WhisperOutput(BaseModel):
    language: str | None = None
    segments: list[_WhisperSegment]


def _to_ms(seconds: float) -> int:
    return max(round(seconds * 1000), 0)


def parse_whisper_output(raw: str, model: str) -> Transcription:
    """Convert Whisper's JSON output into a clean ``Transcription``.

    Segments are ordered by start time but words keep their order inside each
    segment (word timestamps may overlap slightly and must not reorder the
    lyrics). Words are stripped, empty ones dropped and their times made
    strictly increasing: a word never starts before the previous one ends, and
    lasts at least ``MIN_WORD_MS``.

    Args:
        raw: Content of the JSON file written by the Whisper CLI.
        model: Name of the model, recorded in the result.

    Returns:
        The normalized transcription.

    Raises:
        TranscriptionError: If the content is not valid Whisper output.
    """
    try:
        output = _WhisperOutput.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as error:
        raise TranscriptionError("Unreadable Whisper output") from error

    segments = sorted(output.segments, key=lambda segment: segment.start)
    raw_words = [word for segment in segments for word in segment.words]
    words: list[TranscribedWord] = []
    previous_end = 0
    for word in raw_words:
        text = word.word.strip()
        if not text:
            continue
        start = max(_to_ms(word.start), previous_end)
        end = max(_to_ms(word.end), start + MIN_WORD_MS)
        probability = (
            None if word.probability is None else min(max(word.probability, 0.0), 1.0)
        )
        words.append(
            TranscribedWord(
                text=text, start_ms=start, end_ms=end, probability=probability
            )
        )
        previous_end = end

    kept, discarded = remove_known_hallucinations(merge_hyphenated_words(words))
    return Transcription(
        model=model, language=output.language, words=kept, discarded=discarded
    )


def merge_hyphenated_words(words: list[TranscribedWord]) -> list[TranscribedWord]:
    """Join words that Whisper split at hyphens (``cha`` ``-cha`` -> ``cha-cha``).

    A word starting with ``-`` is appended to the previous one; the merged word
    spans both and keeps the lowest probability.

    Args:
        words: Words in lyric order.

    Returns:
        The words with hyphenated parts merged.
    """
    merged: list[TranscribedWord] = []
    for word in words:
        if merged and word.text.startswith("-"):
            previous = merged[-1]
            probabilities = [
                p for p in (previous.probability, word.probability) if p is not None
            ]
            merged[-1] = TranscribedWord(
                text=previous.text + word.text,
                start_ms=previous.start_ms,
                end_ms=word.end_ms,
                probability=min(probabilities) if probabilities else None,
            )
        else:
            merged.append(word)
    return merged


def _normalize_token(text: str) -> str:
    """Casefold and keep only letters and digits, without accents."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if char.isalnum())


_HALLUCINATION_TOKENS = sorted(
    (
        tuple(_normalize_token(token) for token in phrase.split())
        for phrase in KNOWN_HALLUCINATIONS
    ),
    key=len,
    reverse=True,
)


def remove_known_hallucinations(
    words: list[TranscribedWord], min_gap_ms: int = HALLUCINATION_MIN_GAP_MS
) -> tuple[list[TranscribedWord], list[TranscribedWord]]:
    """Drop phrases Whisper typically invents over silence or music.

    A phrase from ``KNOWN_HALLUCINATIONS`` is removed only when it is isolated:
    separated by at least ``min_gap_ms`` (or the start/end of the song) from the
    surrounding words. The same words inside a sung verse are kept.

    Args:
        words: Words in lyric order with increasing times.
        min_gap_ms: Silence required around a phrase to consider it isolated.

    Returns:
        The kept words and the discarded ones.
    """
    tokens = [_normalize_token(word.text) for word in words]
    kept: list[TranscribedWord] = []
    discarded: list[TranscribedWord] = []
    index = 0
    while index < len(words):
        length = _isolated_hallucination_length(words, tokens, index, min_gap_ms)
        if length:
            discarded.extend(words[index : index + length])
            index += length
        else:
            kept.append(words[index])
            index += 1
    return kept, discarded


def _isolated_hallucination_length(
    words: list[TranscribedWord], tokens: list[str], index: int, min_gap_ms: int
) -> int:
    """Return the length of an isolated known phrase starting at ``index``."""
    for phrase in _HALLUCINATION_TOKENS:
        end = index + len(phrase)
        if tuple(tokens[index:end]) != phrase:
            continue
        isolated_before = index == 0 or (
            words[index].start_ms - words[index - 1].end_ms >= min_gap_ms
        )
        isolated_after = end == len(words) or (
            words[end].start_ms - words[end - 1].end_ms >= min_gap_ms
        )
        if isolated_before and isolated_after:
            return len(phrase)
    return 0


class WhisperTranscriber:
    """``Transcriber`` running the OpenAI Whisper CLI in a subprocess.

    Settings are tuned for singing: no conditioning on previous text, which
    avoids repetition loops. Whisper's own hallucination-silence filter is off
    by default because it drops real words in fast lyrics (e.g. rap); known
    hallucinations are removed afterwards by ``remove_known_hallucinations``.
    """

    def __init__(
        self,
        model: str = "large-v3-turbo",
        device: str = "cuda",
        timeout_s: float = 900.0,
        hallucination_silence_s: float | None = None,
        python: str = sys.executable,
    ) -> None:
        """Initialize the transcriber.

        Args:
            model: Whisper model name.
            device: Torch device (``cuda`` or ``cpu``).
            timeout_s: Max seconds for one transcription.
            hallucination_silence_s: Silence threshold for Whisper's own
                hallucination filter, or None to disable it.
            python: Python interpreter with Whisper installed.
        """
        self._model = model
        self._device = device
        self._timeout_s = timeout_s
        self._hallucination_silence_s = hallucination_silence_s
        self._python = python

    @property
    def name(self) -> str:
        """Identifier of the model, e.g. ``whisper-large-v3-turbo``."""
        return f"whisper-{self._model}"

    def command(self, audio: Path, output_dir: Path, language: str | None) -> list[str]:
        """Build the Whisper command line.

        Args:
            audio: Input audio file.
            output_dir: Directory for the JSON output.
            language: Language to force, or None to auto-detect.

        Returns:
            The command and its arguments.
        """
        command = [
            self._python,
            "-m",
            "whisper",
            str(audio),
            "--model",
            self._model,
            "--device",
            self._device,
            "--fp16",
            str(self._device == "cuda"),
            "--word_timestamps",
            "True",
            "--condition_on_previous_text",
            "False",
            "--output_format",
            "json",
            "--output_dir",
            str(output_dir),
            "--verbose",
            "False",
        ]
        if self._hallucination_silence_s is not None:
            command += [
                "--hallucination_silence_threshold",
                str(self._hallucination_silence_s),
            ]
        if language is not None:
            command += ["--language", language]
        return command

    async def transcribe(
        self, audio: Path, output_dir: Path, language: str | None
    ) -> Transcription:
        """Run Whisper. See ``Transcriber``."""
        await anyio.Path(output_dir).mkdir(parents=True, exist_ok=True)
        try:
            await run_tool(
                self.command(audio, output_dir, language), timeout_s=self._timeout_s
            )
        except ToolError as error:
            raise TranscriptionError(f"Whisper failed: {error}") from error

        # The CLI names its output after the input file.
        output_file = anyio.Path(output_dir / f"{audio.stem}.json")
        if not await output_file.is_file():
            raise TranscriptionError(f"Whisper did not produce {output_file.name}")
        return parse_whisper_output(await output_file.read_text("utf-8"), self.name)
