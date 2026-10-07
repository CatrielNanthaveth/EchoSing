"""Running external command-line tools (FFmpeg, ML model CLIs) safely."""

from collections.abc import Sequence
from pathlib import Path

import anyio

STDERR_TAIL_LINES = 20


class ToolError(Exception):
    """An external tool could not be started, failed or timed out.

    Attributes:
        returncode: Exit code of the tool, or None if it never finished.
        stderr_tail: Last lines of the tool's standard error.
    """

    def __init__(
        self, message: str, *, returncode: int | None = None, stderr_tail: str = ""
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description.
            returncode: Exit code of the tool, if it finished.
            stderr_tail: Last lines of standard error, appended to the message.
        """
        full = f"{message}\n{stderr_tail}" if stderr_tail else message
        super().__init__(full)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


async def run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
    """Run a command without blocking the event loop.

    The process is killed if it exceeds the timeout.

    Args:
        args: Executable followed by its arguments (no shell is involved).
        timeout_s: Max seconds the command may run.

    Returns:
        The standard output of the command.

    Raises:
        ToolError: If the command cannot be started, exits with a non-zero
            code or times out.
    """
    command = [str(arg) for arg in args]
    name = Path(command[0]).name
    try:
        with anyio.fail_after(timeout_s):
            result = await anyio.run_process(command, check=False)
    except TimeoutError as error:
        raise ToolError(f"{name} timed out after {timeout_s:g}s") from error
    except OSError as error:
        raise ToolError(f"{name} could not be started: {error}") from error

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip().splitlines()
        raise ToolError(
            f"{name} failed with exit code {result.returncode}",
            returncode=result.returncode,
            stderr_tail="\n".join(stderr[-STDERR_TAIL_LINES:]),
        )
    return result.stdout.decode(errors="replace")
