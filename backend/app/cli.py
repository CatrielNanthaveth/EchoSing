"""Command-line tools for operating the catalog.

Usage (from ``backend/``)::

    uv run python -m app.cli add-song song.mp3 --title "Title" --artist "Artist"
    uv run python -m app.cli set-lyrics <song_id> lyrics.txt
    uv run python -m app.cli run-stage separate <song_id> [--separator roformer]
    uv run python -m app.cli run-stage transcribe <song_id>
    uv run python -m app.cli run-stage segment <song_id>

``run-stage`` runs a single ingestion stage synchronously, without Celery. It is
meant for development and for re-processing one song by hand.
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import anyio
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.enums import SeparationPreset
from app.services.pipeline.segmentation import SegmentationResult, SegmentationStage
from app.services.pipeline.separation import build_separation_stage
from app.services.pipeline.transcription import (
    TranscriptionResult,
    build_transcription_stage,
)
from app.services.song_ingestion import (
    NewSong,
    SongIngestionService,
    SongRegistration,
)
from app.services.song_lyrics import SongLyricsService
from app.storage.base import CHUNK_SIZE
from app.storage.local import LocalStorage
from app.workers.celery_app import celery_app
from app.workers.queue import CeleryJobQueue

STAGES = ("separate", "transcribe", "segment")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Parser with one sub-command per operation.
    """
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    add_song = commands.add_parser("add-song", help="Add a song and queue it")
    add_song.add_argument("path", type=Path, help="Audio file to upload")
    add_song.add_argument("--title", required=True)
    add_song.add_argument("--artist", required=True)
    add_song.add_argument("--language", help="ISO 639-1 code, e.g. 'es'")
    add_song.add_argument(
        "--separator",
        type=SeparationPreset,
        choices=list(SeparationPreset),
        help="Separation preset (default: server setting)",
    )
    add_song.add_argument(
        "--lyrics", type=Path, help="Official lyrics file (UTF-8, one verse per line)"
    )

    set_lyrics = commands.add_parser(
        "set-lyrics", help="Set the official lyrics of a song"
    )
    set_lyrics.add_argument("song_id", type=uuid.UUID)
    set_lyrics.add_argument("path", type=Path, help="Lyrics file (UTF-8)")

    run_stage = commands.add_parser(
        "run-stage", help="Run one ingestion stage for a song, without Celery"
    )
    run_stage.add_argument("stage", choices=STAGES)
    run_stage.add_argument("song_id", type=uuid.UUID)
    run_stage.add_argument(
        "--separator",
        type=SeparationPreset,
        choices=list(SeparationPreset),
        help="Override and save the song's separation preset",
    )
    return parser


async def read_file_chunks(path: Path) -> AsyncIterator[bytes]:
    """Yield the content of a local file in chunks.

    Args:
        path: File to read.

    Yields:
        Chunks of at most ``CHUNK_SIZE`` bytes.
    """
    async with await anyio.open_file(path, "rb") as file:
        while chunk := await file.read(CHUNK_SIZE):
            yield chunk


async def register_file(
    service: SongIngestionService, path: Path, song: NewSong
) -> SongRegistration:
    """Register a local audio file as a new song.

    Args:
        service: Ingestion service to use.
        path: Audio file.
        song: Song metadata.

    Returns:
        The registration result.
    """
    return await service.register_song(song, path.name, read_file_chunks(path))


async def _set_lyrics(
    args: argparse.Namespace, settings: Settings, lyrics: str
) -> BaseModel:
    """Wire the real dependencies and save a song's lyrics."""
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            return await SongLyricsService(session).set_lyrics(args.song_id, lyrics)
    finally:
        await engine.dispose()


async def _add_song(
    args: argparse.Namespace, settings: Settings, lyrics: str | None
) -> BaseModel:
    """Wire the real dependencies and register the song."""
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            service = SongIngestionService(
                session,
                LocalStorage(settings.storage_root),
                CeleryJobQueue(celery_app),
                settings.max_upload_bytes,
                settings.default_separation_preset,
            )
            song = NewSong(
                title=args.title,
                artist=args.artist,
                language=args.language,
                separation_preset=args.separator,
                lyrics=lyrics,
            )
            return await register_file(service, args.path, song)
    finally:
        await engine.dispose()


async def _run_stage(args: argparse.Namespace, settings: Settings) -> BaseModel:
    """Wire the real dependencies and run one ingestion stage."""
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            storage = LocalStorage(settings.storage_root)
            if args.stage == "segment":
                return await SegmentationStage(session, storage).run(args.song_id)
            if args.stage == "transcribe":
                transcription = build_transcription_stage(session, storage, settings)
                return await transcription.run(args.song_id)
            separation = build_separation_stage(session, storage, settings)
            return await separation.run(args.song_id, args.separator)
    finally:
        await engine.dispose()


def _format_ms(ms: int) -> str:
    minutes, seconds = divmod(ms / 1000, 60)
    return f"{int(minutes)}:{seconds:05.2f}"


def summarize(result: BaseModel) -> str:
    """Render a command result for the terminal.

    Transcriptions and lyric lines can be long, so they are rendered as text;
    the full result is saved by the stage. Anything else is shown as JSON.

    Args:
        result: Result returned by a command.

    Returns:
        Text to print.
    """
    if isinstance(result, SegmentationResult):
        lines = result.lyrics.lines
        header = [
            f"source: {result.lyrics.source} | lines: {len(lines)} "
            f"| saved to: {result.artifact_key}"
        ]
        report = result.lyrics.alignment
        if report is not None:
            header.append(
                f"alignment: {report.matched_words}/{report.lyric_words} words "
                f"matched ({report.match_ratio:.0%}), {report.replaced_words} "
                f"replaced, {report.interpolated_words} interpolated, "
                f"{report.unused_transcribed_words} transcribed words unused"
            )
        return "\n".join(
            header
            + [
                f"{line.index:>3} [{_format_ms(line.start_ms)} - "
                f"{_format_ms(line.end_ms)}] {line.text}"
                for line in lines
            ]
        )
    if not isinstance(result, TranscriptionResult):
        return result.model_dump_json(indent=2)
    transcription = result.transcription
    first_words = ", ".join(
        f"{word.text}@{word.start_ms / 1000:.2f}s" for word in transcription.words[:8]
    )
    return "\n".join(
        [
            f"model: {transcription.model} | language: {transcription.language}",
            f"words: {len(transcription.words)} | saved to: {result.artifact_key}",
            f"first words: {first_words}",
            "discarded as hallucinations: "
            + (" ".join(w.text for w in transcription.discarded) or "(none)"),
            "text:",
            transcription.text,
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-stage" and args.separator and args.stage != "separate":
        parser.error("--separator only applies to the 'separate' stage")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    if args.command in ("add-song", "set-lyrics"):
        lyrics_path = args.path if args.command == "set-lyrics" else args.lyrics
        for path in (args.path, lyrics_path):
            if path is not None and not path.is_file():
                print(f"File not found: {path}", file=sys.stderr)
                return 1
        if args.command == "set-lyrics":
            lyrics_text = args.path.read_text("utf-8")
            result = asyncio.run(_set_lyrics(args, settings, lyrics_text))
        else:
            lyrics = lyrics_path.read_text("utf-8") if lyrics_path else None
            result = asyncio.run(_add_song(args, settings, lyrics))
    else:
        started = time.perf_counter()
        result = asyncio.run(_run_stage(args, settings))
        print(f"Stage '{args.stage}' took {time.perf_counter() - started:.1f}s")

    print(summarize(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
