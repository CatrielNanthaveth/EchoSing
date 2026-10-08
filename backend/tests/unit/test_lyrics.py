import random

import pytest

from app.ml.transcription import TranscribedWord
from app.schemas.analysis import PipelineInfo, PitchCurve, SongAnalysisData
from app.services.lyrics import SegmentationConfig, segment_lines

CONFIG = SegmentationConfig()


def words_from(text: str, start: int = 0, step: int = 400) -> list[TranscribedWord]:
    """Contiguous words, one every ``step`` ms (like Whisper output)."""
    return [
        TranscribedWord(
            text=token, start_ms=start + i * step, end_ms=start + (i + 1) * step
        )
        for i, token in enumerate(text.split())
    ]


def line_texts(
    words: list[TranscribedWord], config: SegmentationConfig = CONFIG
) -> list[str]:
    return [line.text for line in segment_lines(words, config)]


# --- edge cases --------------------------------------------------------------


def test_no_words_no_lines() -> None:
    assert segment_lines([]) == []


def test_single_word_is_one_line() -> None:
    lines = segment_lines(words_from("Hola"))

    assert [(line.index, line.text) for line in lines] == [(0, "Hola")]


def test_text_without_any_cue_is_split_only_by_length() -> None:
    words = words_from(" ".join(["la"] * 40), step=300)  # 12 s, 40 words

    lines = segment_lines(words)

    assert len(lines) > 1
    assert all(len(line.words) <= CONFIG.max_line_words for line in lines)


# --- verse cues --------------------------------------------------------------


def test_capitalized_word_starts_a_new_line() -> None:
    assert line_texts(words_from("dame vida y aliento Que me obligue a renacer")) == [
        "dame vida y aliento",
        "Que me obligue a renacer",
    ]


def test_consecutive_capitals_are_a_proper_noun() -> None:
    assert line_texts(words_from("Busco a mi Peter Pan siempre")) == [
        "Busco a mi Peter Pan siempre"
    ]


def test_verse_starter_after_proper_noun_starts_a_line() -> None:
    assert line_texts(words_from("me siento un Peter Pan Que ha jugado tanto")) == [
        "me siento un Peter Pan",
        "Que ha jugado tanto",
    ]


def test_capital_after_article_or_preposition_is_a_proper_noun() -> None:
    assert line_texts(words_from("cruzamos juntos por los Andes nevados")) == [
        "cruzamos juntos por los Andes nevados"
    ]


def test_capital_after_comma_starts_a_line() -> None:
    assert line_texts(words_from("Sigo vivo, Créeme mi amor", step=500)) == [
        "Sigo vivo,",
        "Créeme mi amor",
    ]


def test_sentence_end_starts_a_line() -> None:
    assert line_texts(words_from("es mi tiempo. luego sigo cantando")) == [
        "es mi tiempo.",
        "luego sigo cantando",
    ]


def test_inverted_marks_start_a_line() -> None:
    assert line_texts(words_from("me preguntas siempre ¿cómo estás hoy")) == [
        "me preguntas siempre",
        "¿cómo estás hoy",
    ]


@pytest.mark.parametrize(("gap", "expected_lines"), [(999, 1), (1000, 2)])
def test_long_pause_starts_a_line(gap: int, expected_lines: int) -> None:
    first = words_from("canto esta parte")
    second = words_from("y sigo cantando", start=first[-1].end_ms + gap)

    assert len(segment_lines(first + second)) == expected_lines


# --- long lines --------------------------------------------------------------


def test_long_line_is_split_at_a_comma() -> None:
    text = "desde el faro de las dudas, deslumbrando cada adiós desde las notas mudas"
    words = words_from(text, step=700)  # 13 words, 9.1 s > 8 s

    assert line_texts(words) == [
        "desde el faro de las dudas,",
        "deslumbrando cada adiós desde las notas mudas",
    ]


def test_long_line_is_not_split_after_a_preposition() -> None:
    words = words_from("no hay motivos para decirnos adiós tan pronto", step=1200)

    lines = line_texts(words)

    assert len(lines) == 2
    assert not lines[0].endswith("para")


def test_long_line_is_split_at_the_largest_pause() -> None:
    first = words_from("canto esta parte muy lento", step=1000)
    second = words_from("y sigo después", start=first[-1].end_ms + 600, step=1000)

    assert line_texts(first + second) == [
        "canto esta parte muy lento",
        "y sigo después",
    ]


def test_too_many_words_are_split_even_if_short() -> None:
    words = words_from(" ".join(f"w{i}" for i in range(20)), step=100)

    lines = segment_lines(words)

    assert len(lines) >= 2
    assert all(len(line.words) <= CONFIG.max_line_words for line in lines)


# --- short lines -------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap_before", "gap_after", "expected"),
    [
        (0, 500, ["dame tu vida Oh,", "Que te quiero"]),
        (500, 0, ["dame tu vida", "Oh, Que te quiero"]),
    ],
)
def test_one_word_line_is_merged_into_the_closest_neighbor(
    gap_before: int, gap_after: int, expected: list[str]
) -> None:
    before = words_from("dame tu vida")
    oh = words_from("Oh,", start=before[-1].end_ms + gap_before)
    after = words_from("Que te quiero", start=oh[-1].end_ms + gap_after)

    assert line_texts(before + oh + after) == expected


def test_short_line_is_not_merged_across_a_long_pause() -> None:
    first = words_from("Hola")
    second = words_from("ahora canto la canción entera", start=first[-1].end_ms + 3000)

    assert line_texts(first + second) == ["Hola", "ahora canto la canción entera"]


def test_short_line_is_not_merged_if_the_result_is_too_long() -> None:
    config = SegmentationConfig(max_line_words=4)
    words = words_from("Uno dos tres cuatro Cinco")

    assert line_texts(words, config) == ["Uno dos tres cuatro", "Cinco"]


# --- invariants on random input -----------------------------------------------


def _random_words(rng: random.Random, count: int) -> list[TranscribedWord]:
    vocabulary = [
        "la",
        "noche",
        "Que",
        "Y",
        "vida",
        "para",
        "tiempo,",
        "voz.",
        "¿cómo",
        "Peter",
    ]
    words: list[TranscribedWord] = []
    time = 0
    for _ in range(count):
        time += rng.choice([0, 0, 0, 50, 300, 1200, 4000])
        duration = rng.randint(80, 900)
        words.append(
            TranscribedWord(
                text=rng.choice(vocabulary), start_ms=time, end_ms=time + duration
            )
        )
        time += duration
    return words


@pytest.mark.parametrize("seed", range(25))
def test_random_input_keeps_every_invariant(seed: int) -> None:
    rng = random.Random(seed)
    words = _random_words(rng, rng.randint(1, 300))

    lines = segment_lines(words)

    flat = [word for line in lines for word in line.words]
    assert [(w.text, w.start_ms, w.end_ms) for w in flat] == [
        (w.text, w.start_ms, w.end_ms) for w in words
    ]
    for line in lines:
        if len(line.words) > 1:
            assert line.end_ms - line.start_ms <= CONFIG.max_line_ms
            assert len(line.words) <= CONFIG.max_line_words
    # The lines must satisfy every invariant of the stored analysis format.
    SongAnalysisData(
        duration_ms=words[-1].end_ms,
        pipeline=PipelineInfo(separator="s", transcriber="t", pitch_extractor="p"),
        lines=lines,
        pitch=PitchCurve(hop_ms=10, midi=[], confidence=[]),
    )
