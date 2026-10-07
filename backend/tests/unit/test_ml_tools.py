import sys
import time

import pytest

from app.ml.tools import ToolError, run_tool

PYTHON = sys.executable


async def test_returns_stdout_on_success() -> None:
    output = await run_tool([PYTHON, "-c", "print('hello')"], timeout_s=30)

    assert output.strip() == "hello"


async def test_non_zero_exit_raises_with_stderr_tail() -> None:
    script = (
        "import sys; "
        "print('\\n'.join(f'line {i}' for i in range(50)), file=sys.stderr); "
        "sys.exit(3)"
    )

    with pytest.raises(ToolError) as excinfo:
        await run_tool([PYTHON, "-c", script], timeout_s=30)

    error = excinfo.value
    assert error.returncode == 3
    assert "exit code 3" in str(error)
    assert error.stderr_tail.splitlines()[-1] == "line 49"
    assert "line 29" not in error.stderr_tail  # only the last 20 lines


async def test_timeout_kills_the_process() -> None:
    started = time.perf_counter()

    with pytest.raises(ToolError, match="timed out"):
        await run_tool([PYTHON, "-c", "import time; time.sleep(30)"], timeout_s=0.5)

    assert time.perf_counter() - started < 10


async def test_missing_executable_raises() -> None:
    with pytest.raises(ToolError, match="could not be started"):
        await run_tool(["definitely-not-a-real-tool-xyz"], timeout_s=5)
