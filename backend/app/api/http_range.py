"""Parsing of HTTP ``Range`` request headers (RFC 9110, single byte ranges)."""

import re

from pydantic import BaseModel

_SINGLE_RANGE = re.compile(r"(\d*)-(\d*)")


class ByteRange(BaseModel):
    """A satisfiable range of bytes.

    Attributes:
        start: First byte (inclusive).
        stop: End (exclusive), so the length is ``stop - start``.
    """

    start: int
    stop: int

    def content_range(self, size: int) -> str:
        """Render the ``Content-Range`` header value for this range.

        Args:
            size: Total size of the resource.

        Returns:
            A value like ``bytes 0-499/1234``.
        """
        return f"bytes {self.start}-{self.stop - 1}/{size}"


class RangeNotSatisfiableError(Exception):
    """The requested range does not overlap the resource (HTTP 416)."""


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """Parse a ``Range`` header for a resource of ``size`` bytes.

    Supports ``bytes=a-b``, ``bytes=a-`` (to the end) and ``bytes=-n`` (the
    last n bytes); an end beyond the resource is clamped. As the RFC allows,
    headers that are missing, malformed, not in bytes or with several ranges
    are ignored, meaning the whole resource is served.

    Args:
        header: Value of the ``Range`` header, if any.
        size: Size of the resource in bytes.

    Returns:
        The range to serve, or None to serve the whole resource.

    Raises:
        RangeNotSatisfiableError: If the range is well formed but starts at or
            after the end of the resource, or asks for zero bytes.
    """
    if header is None or not header.startswith("bytes="):
        return None
    spec = header.removeprefix("bytes=").strip()
    match = _SINGLE_RANGE.fullmatch(spec)
    if match is None:  # malformed or several ranges
        return None
    first, last = match.groups()

    if not first:
        if not last:
            return None
        suffix = int(last)
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(spec)
        return ByteRange(start=max(size - suffix, 0), stop=size)

    start = int(first)
    if last and int(last) < start:
        return None  # invalid range: ignored
    if start >= size:
        raise RangeNotSatisfiableError(spec)
    stop = min(int(last) + 1, size) if last else size
    return ByteRange(start=start, stop=stop)
