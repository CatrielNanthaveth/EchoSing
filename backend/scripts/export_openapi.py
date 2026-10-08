"""Export the API contract (OpenAPI) for the web client's generated types.

Usage (from ``backend/``)::

    uv run python -m scripts.export_openapi ../web/openapi.json

The WebSocket messages are not part of the HTTP API, so their schemas are added
to ``components.schemas`` to type the real-time protocol as well. The app is
built without starting it: no database or Redis is needed.
"""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.main import create_app
from app.schemas.sessions import (
    ErrorMessage,
    FinishMessage,
    LinePitchMessage,
    LineScoreMessage,
    ReadyMessage,
    SessionSummaryMessage,
)

WEBSOCKET_MESSAGES: tuple[type[BaseModel], ...] = (
    LinePitchMessage,
    FinishMessage,
    ReadyMessage,
    LineScoreMessage,
    ErrorMessage,
    SessionSummaryMessage,
)


def build_contract() -> dict[str, Any]:
    """Build the OpenAPI document plus the WebSocket message schemas.

    Returns:
        The OpenAPI document as a JSON-compatible dict.
    """
    document = create_app().openapi()
    _, messages = models_json_schema(
        [(model, "serialization") for model in WEBSOCKET_MESSAGES],
        ref_template="#/components/schemas/{model}",
    )
    schemas: dict[str, Any] = document.setdefault("components", {}).setdefault(
        "schemas", {}
    )
    for name, schema in messages.get("$defs", {}).items():
        schemas.setdefault(name, schema)
    return document


def main(argv: list[str]) -> int:
    """Write the contract to the path given as the only argument.

    Args:
        argv: Command-line arguments, without the program name.

    Returns:
        The process exit code.
    """
    if len(argv) != 1:
        print("usage: python -m scripts.export_openapi <output.json>", file=sys.stderr)
        return 2
    output = Path(argv[0])
    output.write_text(
        json.dumps(build_contract(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
