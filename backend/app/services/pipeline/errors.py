"""Errors shared by the ingestion pipeline stages."""


class StageError(Exception):
    """A pipeline stage cannot run (e.g. missing song or missing input asset)."""
