import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.ml import transcription
from app.ml.tools import ToolError
from app.ml.transcription import (
    MIN_WORD_MS,
    TranscribedWord,
    TranscriptionError,
    WhisperTranscriber,
    merge_hyphenated_words,
    parse_whisper_output,
    remove_known_hallucinations,
)
from tests.conftest import FIXTURES_DIR

WHISPER_OUTPUT = (FIXTURES_DIR / "whisper_output.json").read_text("utf-8")


def _transcriber(device: str = "cuda") -> WhisperTranscriber:
    return WhisperTranscriber(
        model="large-v3-turbo",
        device=device,
        timeout_s=60,
        hallucination_silence_s=2.0,
        python="py",
    )


# --- parsing and normalization -----------------------------------------------


def test_parse_flattens_sorts_and_cleans_words() -> None:
    result = parse_whisper_output(WHISPER_OUTPUT, "whisper-test")

    assert result.model == "whisper-test"
    assert result.language == "es"
    assert [w.text for w in result.words] == [
        "Dame",
        "de",
        "tu",
        "vida",
        "y",
        "de",
        "tu",
        "tiempo.",
        "Suficientes",
        "para",
        "ver",
    ]
    assert result.text.startswith("Dame de tu vida")


def test_parse_converts_seconds_to_ms() -> None:
    words = parse_whisper_output(WHISPER_OUTPUT, "m").words

    assert (words[0].start_ms, words[0].end_ms) == (19660, 20100)
    assert (words[-1].start_ms, words[-1].end_ms) == (27500, 28080)


def test_parse_makes_words_strictly_increasing() -> None:
    words = parse_whisper_output(WHISPER_OUTPUT, "m").words

    # " de" had zero duration and the next " tu" started before it ended:
    # the lyric order is kept and only the times are adjusted.
    de, tu = words[1], words[2]
    assert (de.text, tu.text) == ("de", "tu")
    assert de.end_ms == de.start_ms + MIN_WORD_MS
    assert tu.start_ms == de.end_ms
    for previous, current in zip(words, words[1:], strict=False):
        assert current.start_ms >= previous.end_ms
    assert all(w.end_ms > w.start_ms for w in words)


def test_parse_keeps_and_clamps_probabilities() -> None:
    words = parse_whisper_output(WHISPER_OUTPUT, "m").words

    assert words[0].probability == 0.95
    assert words[4].probability is None  # " y" had no probability
    assert words[-1].probability == 1.0  # 1.0000001 clamped


def test_parse_without_words_returns_empty_transcription() -> None:
    result = parse_whisper_output('{"segments": [], "language": null}', "m")

    assert result.words == []
    assert result.language is None
    assert result.text == ""


@pytest.mark.parametrize("raw", ["not json", '{"language": "es"}', "[]"])
def test_parse_rejects_invalid_output(raw: str) -> None:
    with pytest.raises(TranscriptionError):
        parse_whisper_output(raw, "m")


# --- command -----------------------------------------------------------------


def test_command_uses_singing_friendly_options() -> None:
    command = _transcriber().command(Path("in/vocals.flac"), Path("out"), "es")

    assert command[:4] == ["py", "-m", "whisper", str(Path("in/vocals.flac"))]
    assert command[command.index("--model") + 1] == "large-v3-turbo"
    assert command[command.index("--device") + 1] == "cuda"
    assert command[command.index("--fp16") + 1] == "True"
    assert command[command.index("--word_timestamps") + 1] == "True"
    assert command[command.index("--condition_on_previous_text") + 1] == "False"
    assert command[command.index("--hallucination_silence_threshold") + 1] == "2.0"
    assert command[command.index("--output_format") + 1] == "json"
    assert command[command.index("--output_dir") + 1] == "out"
    assert command[command.index("--language") + 1] == "es"


def test_command_without_language_lets_whisper_detect_it() -> None:
    command = _transcriber().command(Path("vocals.flac"), Path("out"), None)

    assert "--language" not in command


def test_fp16_is_disabled_on_cpu() -> None:
    command = _transcriber("cpu").command(Path("vocals.flac"), Path("out"), None)

    assert command[command.index("--fp16") + 1] == "False"


def test_name_includes_the_model() -> None:
    assert _transcriber().name == "whisper-large-v3-turbo"


# --- transcribe --------------------------------------------------------------


async def test_transcribe_reads_the_output_named_after_the_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        (tmp_path / "vocals.json").write_text(WHISPER_OUTPUT, "utf-8")
        return ""

    monkeypatch.setattr(transcription, "run_tool", fake_run_tool)

    result = await _transcriber().transcribe(Path("x/vocals.flac"), tmp_path, "es")

    assert result.model == "whisper-large-v3-turbo"
    assert len(result.words) == 11


async def test_transcribe_missing_output_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        return ""

    monkeypatch.setattr(transcription, "run_tool", fake_run_tool)

    with pytest.raises(TranscriptionError, match="vocals.json"):
        await _transcriber().transcribe(Path("vocals.flac"), tmp_path, None)


async def test_transcribe_tool_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def failing_run_tool(args: Sequence[str | Path], *, timeout_s: float) -> str:
        raise ToolError("py failed", returncode=1, stderr_tail="CUDA out of memory")

    monkeypatch.setattr(transcription, "run_tool", failing_run_tool)

    with pytest.raises(TranscriptionError, match="CUDA out of memory"):
        await _transcriber().transcribe(Path("vocals.flac"), tmp_path, None)


# --- hyphenated words --------------------------------------------------------


def _w(text: str, start: int, end: int, p: float | None = 0.9) -> TranscribedWord:
    return TranscribedWord(text=text, start_ms=start, end_ms=end, probability=p)


def test_hyphenated_parts_are_merged_into_one_word() -> None:
    words = [
        _w("un", 0, 100),
        _w("cha", 100, 200, 0.99),
        _w("-cha", 200, 300, 0.6),
        _w("-cha,", 300, 450, 0.8),
        _w("yo", 500, 600),
    ]

    merged = merge_hyphenated_words(words)

    assert [w.text for w in merged] == ["un", "cha-cha-cha,", "yo"]
    assert (merged[1].start_ms, merged[1].end_ms) == (100, 450)
    assert merged[1].probability == 0.6


def test_leading_hyphen_without_previous_word_is_kept() -> None:
    assert [w.text for w in merge_hyphenated_words([_w("-hola", 0, 100)])] == ["-hola"]


def test_merge_with_unknown_probabilities() -> None:
    merged = merge_hyphenated_words(
        [_w("cha", 0, 100, None), _w("-cha", 100, 200, None)]
    )

    assert merged[0].probability is None


# --- known hallucinations ----------------------------------------------------


def _phrase(text: str, start: int, step: int = 200) -> list[TranscribedWord]:
    return [
        _w(token, start + i * step, start + (i + 1) * step)
        for i, token in enumerate(text.split())
    ]


def test_isolated_trailing_hallucination_is_discarded() -> None:
    lyrics = _phrase("te puedo enamorar", 200_000)
    outro = _phrase("Gracias por ver el video.", 213_460)  # 8.4 s of silence before

    kept, discarded = remove_known_hallucinations(lyrics + outro)

    assert [w.text for w in kept] == ["te", "puedo", "enamorar"]
    assert [w.text for w in discarded] == ["Gracias", "por", "ver", "el", "video."]


def test_matching_ignores_case_accents_and_punctuation() -> None:
    words = _phrase("Subtítulos realizados por la comunidad de Amara.org", 0)

    kept, discarded = remove_known_hallucinations(words)

    assert kept == []
    assert len(discarded) == 7


def test_phrase_inside_a_verse_is_kept() -> None:
    words = _phrase("y te digo gracias por ver lo que nadie vio", 10_000)

    kept, discarded = remove_known_hallucinations(words)

    assert discarded == []
    assert len(kept) == len(words)


def test_phrase_needs_silence_on_both_sides() -> None:
    before = _phrase("hola", 0)
    hallucination = _phrase("thanks for watching", 5_000)  # isolated before...
    after = _phrase("seguimos cantando", 5_700)  # ...but not after

    kept, discarded = remove_known_hallucinations(before + hallucination + after)

    assert discarded == []
    assert len(kept) == 6


def test_parse_applies_merging_and_hallucination_filter() -> None:
    raw = json.dumps(
        {
            "language": "es",
            "segments": [
                {
                    "start": 1.0,
                    "words": [
                        {"word": " un", "start": 1.0, "end": 1.2, "probability": 0.9},
                        {"word": " cha", "start": 1.2, "end": 1.4, "probability": 0.9},
                        {"word": " -cha", "start": 1.4, "end": 1.6, "probability": 0.8},
                    ],
                },
                {
                    "start": 10.0,
                    "words": [
                        {"word": " Gracias", "start": 10.0, "end": 10.3},
                        {"word": " por", "start": 10.3, "end": 10.4},
                        {"word": " ver.", "start": 10.4, "end": 10.9},
                    ],
                },
            ],
        }
    )

    result = parse_whisper_output(raw, "m")

    assert result.text == "un cha-cha"
    assert [w.text for w in result.discarded] == ["Gracias", "por", "ver."]
