"""Command-line tools for operating the catalog.

Usage (from ``backend/``)::

    uv run python -m app.cli add-song song.mp3 --title "Title" --artist "Artist"
    uv run python -m app.cli run-stage separate <song_id> [--separator roformer]

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
from app.services.pipeline.separation import build_separation_stage
from app.services.song_ingestion import (
    NewSong,
    SongIngestionService,
    SongRegistration,
)
from app.storage.base import CHUNK_SIZE
from app.storage.local import LocalStorage
from app.workers.celery_app import celery_app
from app.workers.queue import CeleryJobQueue

STAGES = ("separate",)


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


async def _add_song(args: argparse.Namespace, settings: Settings) -> BaseModel:
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
            stage = build_separation_stage(session, storage, settings)
            return await stage.run(args.song_id, args.separator)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    if args.command == "add-song":
        if not args.path.is_file():
            print(f"File not found: {args.path}", file=sys.stderr)
            return 1
        result = asyncio.run(_add_song(args, settings))
    else:
        started = time.perf_counter()
        result = asyncio.run(_run_stage(args, settings))
        print(f"Stage '{args.stage}' took {time.perf_counter() - started:.1f}s")

    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
