"""Command-line tools for operating the catalog.

Usage (from ``backend/``)::

    uv run python -m app.cli add-song song.mp3 --title "Title" --artist "Artist"
"""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import anyio

from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.song_ingestion import (
    NewSong,
    SongIngestionService,
    SongRegistration,
)
from app.storage.base import CHUNK_SIZE
from app.storage.local import LocalStorage
from app.workers.celery_app import celery_app
from app.workers.queue import CeleryJobQueue


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


async def _add_song(args: argparse.Namespace) -> SongRegistration:
    """Wire the real dependencies and register the song."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            service = SongIngestionService(
                session,
                LocalStorage(settings.storage_root),
                CeleryJobQueue(celery_app),
                settings.max_upload_bytes,
            )
            song = NewSong(title=args.title, artist=args.artist, language=args.language)
            return await register_file(service, args.path, song)
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
    if not args.path.is_file():
        print(f"File not found: {args.path}", file=sys.stderr)
        return 1
    registration = asyncio.run(_add_song(args))
    print(registration.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
