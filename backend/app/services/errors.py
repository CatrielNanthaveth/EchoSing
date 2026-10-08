"""Domain errors shared by the application services."""


class SongNotFoundError(Exception):
    """The requested song does not exist."""
