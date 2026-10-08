"""Response schemas of the public song catalog."""

import uuid

from pydantic import BaseModel

from app.schemas.analysis import LyricLine


class SongSummary(BaseModel):
    """A playable song as listed in the catalog.

    Attributes:
        id: Song id.
        title: Song title.
        artist: Performing artist.
        language: ISO 639-1 code of the lyrics, if known.
        duration_ms: Duration of the song.
        line_count: Number of lyric lines (scoring units).
        reprocessing: True while a newer analysis is being produced; the song
            stays playable with its current one.
    """

    id: uuid.UUID
    title: str
    artist: str
    language: str | None
    duration_ms: int | None
    line_count: int
    reprocessing: bool


class SongPage(BaseModel):
    """A page of catalog songs.

    Attributes:
        items: Songs in this page, ordered by title.
        total: Songs matching the query across all pages.
        limit: Max songs per page requested.
        offset: Songs skipped before this page.
    """

    items: list[SongSummary]
    total: int
    limit: int
    offset: int


class SongDetail(SongSummary):
    """A playable song with its synced lyrics.

    Attributes:
        analysis_id: Id of the current analysis; play sessions are bound to it.
        analysis_version: Version number of the current analysis.
        lines: Lyric lines with timed words (the pitch curve is served apart).
    """

    analysis_id: uuid.UUID
    analysis_version: int
    lines: list[LyricLine]
