import json
from pathlib import Path

import pytest

from scripts.export_openapi import build_contract, main


def test_contract_includes_http_paths_and_websocket_messages() -> None:
    contract = build_contract()

    assert "/songs/{song_id}" in contract["paths"]
    assert "/sessions" in contract["paths"]
    schemas = contract["components"]["schemas"]
    for name in (
        "LinePitchMessage",
        "FinishMessage",
        "ReadyMessage",
        "LineScoreMessage",
        "ErrorMessage",
        "SessionSummaryMessage",
        "ErrorCode",
    ):
        assert name in schemas
    assert "$defs" not in json.dumps(contract)


def test_main_writes_the_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "openapi.json"

    assert main([str(output)]) == 0

    assert json.loads(output.read_text(encoding="utf-8"))["info"]["title"] == (
        "EchoSing API"
    )
    assert "Wrote" in capsys.readouterr().out


def test_main_requires_an_output_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err
