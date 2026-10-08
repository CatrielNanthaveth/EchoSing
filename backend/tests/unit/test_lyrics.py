import random

import pytest

from app.ml.transcription import TranscribedWord
from app.schemas.analysis import PipelineInfo, PitchCurve, SongAnalysisData
from app.services.lyrics import (
    FALLBACK_WORD_MS,
    MIN_ALIGNED_WORD_MS,
    LyricsMismatchError,
    SegmentationConfig,
    align_lyrics,
    is_near_word,
    normalize_word,
    parse_lyrics_text,
    segment_lines,
)

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


# --- official lyrics: parsing --------------------------------------------------


def test_parse_lyrics_skips_blank_lines_labels_and_backing_vocals() -> None:
    text = """[Verso 1]
Dame de tu vida   y de tu tiempo

Suficientes para ver
(Tan solo un momentito más, mi amor)
  [Coro]
Que me obligue a renacer
"""

    assert parse_lyrics_text(text) == [
        "Dame de tu vida y de tu tiempo",
        "Suficientes para ver",
        "Que me obligue a renacer",
    ]


@pytest.mark.parametrize(
    ("word", "key"),
    [
        ("Créemelo,", "creemelo"),
        ("¿Cómo", "como"),
        ("chachachá", "chachacha"),
        ("cha-cha-cha", "chachacha"),
        ("déjà", "deja"),
        ("Peter", "peter"),
        ("...", ""),
    ],
)
def test_normalize_word(word: str, key: str) -> None:
    assert normalize_word(word) == key


# --- official lyrics: alignment --------------------------------------------------


def aligned_texts(lines: list[str], heard: str, step: int = 300) -> list[list[str]]:
    result = align_lyrics(lines, words_from(heard, step=step))
    return [[word.text for word in line.words] for line in result.lines]


def test_perfect_match_takes_transcribed_times() -> None:
    heard = words_from("dame de tu vida que me obligue")

    result = align_lyrics(["Dame de tu vida", "Que me obligue"], heard)

    assert [line.text for line in result.lines] == ["Dame de tu vida", "Que me obligue"]
    flat = [word for line in result.lines for word in line.words]
    assert [(w.start_ms, w.end_ms) for w in flat] == [
        (w.start_ms, w.end_ms) for w in heard
    ]
    assert result.report.matched_words == 7
    assert result.report.match_ratio == 1.0


def test_official_text_is_kept_exactly() -> None:
    result = align_lyrics(
        ["¿Cómo quieres, mi amor?", "Ir a bailar un chachachá"],
        words_from("Como quieres mi amor ir a bailar un cha-cha-cha"),
    )

    assert [line.text for line in result.lines] == [
        "¿Cómo quieres, mi amor?",
        "Ir a bailar un chachachá",
    ]
    assert result.report.matched_words == 9


def test_words_missed_by_the_transcriber_are_interpolated() -> None:
    # Real case: Whisper (with its silence filter) skipped "si de pequeño".
    lines = ["Pero estaré donde señales", "Si de pequeño nunca me até los cordones"]
    heard = words_from("Pero estaré donde señales nunca me até los cordones")

    result = align_lyrics(lines, heard)

    second = result.lines[1].words
    assert [w.text for w in second[:3]] == ["Si", "de", "pequeño"]
    assert result.report.interpolated_words == 3
    flat = [w for line in result.lines for w in line.words]
    for previous, current in zip(flat, flat[1:], strict=False):
        assert current.start_ms >= previous.end_ms
        assert current.end_ms > current.start_ms


def test_interpolation_uses_a_real_gap_when_available() -> None:
    before = words_from("no estuvimos por los pelos")
    after = words_from("nunca me ate", start=before[-1].end_ms + 1000)

    result = align_lyrics(
        ["No estuvimos por los pelos", "Si de pequeño nunca me ate"], before + after
    )

    interpolated = result.lines[1].words[:3]
    assert interpolated[0].start_ms == before[-1].end_ms
    assert interpolated[-1].end_ms == after[0].start_ms


def test_misheard_words_share_the_time_of_what_was_heard() -> None:
    lines = ["Y acabé empezando esta canción"]
    heard = words_from("y saqué empezando esta canción")

    result = align_lyrics(lines, heard)

    acabe = result.lines[0].words[1]
    assert acabe.text == "acabé"
    assert (acabe.start_ms, acabe.end_ms) == (heard[1].start_ms, heard[1].end_ms)
    assert result.report.replaced_words == 1


@pytest.mark.parametrize(
    ("official", "heard", "near"),
    [
        ("feli", "feliz", True),  # "feli'": elided final letter
        ("cosa", "cosas", True),
        ("lao", "lado", True),  # "la'o"
        ("ve", "vez", True),
        ("nera", "negra", True),  # one letter misheard
        ("acabe", "acaba", True),
        ("de", "te", False),  # two-letter words are too ambiguous
        ("vida", "vida", False),  # identical: an exact match, not a near one
        ("lado", "la", False),
        ("negra", "nada", False),
        ("", "a", False),
    ],
)
def test_is_near_word(official: str, heard: str, near: bool) -> None:
    assert is_near_word(official, heard) is near


def test_near_words_take_the_transcribed_times() -> None:
    lines = ["Quiero verte feli'", "Mejor si es al la'o de mí"]
    heard = words_from("quiero verte feliz mejor si es al lado de mí")

    result = align_lyrics(lines, heard)

    flat = [word for line in result.lines for word in line.words]
    assert [(w.start_ms, w.end_ms) for w in flat] == [
        (w.start_ms, w.end_ms) for w in heard
    ]
    assert result.lines[0].words[2].text == "feli'"
    assert result.report.near_matched_words == 2
    assert result.report.matched_words == 8
    assert result.report.match_ratio == 1.0


def test_extra_transcribed_words_are_ignored() -> None:
    result = align_lyrics(
        ["Dame de tu vida"], words_from("eh dame de tu vida gracias por ver el video")
    )

    assert result.lines[0].text == "Dame de tu vida"
    assert result.report.unused_transcribed_words == 6


def test_repeated_chorus_is_aligned_in_order() -> None:
    chorus = "no hay motivos para decirnos adiós"
    heard = words_from(f"{chorus} sigo vivo {chorus}")

    result = align_lyrics(
        [
            "No hay motivos para decirnos adiós",
            "Sigo vivo",
            "No hay motivos para decirnos adiós",
        ],
        heard,
    )

    assert (
        result.lines[0].start_ms < result.lines[1].start_ms < result.lines[2].start_ms
    )
    assert result.lines[2].start_ms == heard[8].start_ms


def test_choruses_repeated_many_times_are_paired_in_order() -> None:
    # Real case ("Rara vez"): a greedy longest-block matcher paired the first
    # chorus of the lyrics with the third one of the recording, so everything
    # in between went unmatched and only 34% of the words matched.
    # Whisper misheard the first choruses and got the last ones right, so the
    # longest exact block pairs lyric choruses 1-2 with recorded choruses 3-4.
    verse = ["Negra rara vez te vi bien", "Estando con aquel"]
    chorus = [
        "Sos lo que me da paz",
        "Lo que andaba buscando",
        "Y esa felicidad",
        "Que hace que ande sonriendo",
    ]
    bridge = ["Dama con fama y cama alta gama"]
    lines = verse + chorus + chorus + bridge + verse + chorus + chorus
    heard_verse = "Nera rara ve te vi ventando con aquel"
    misheard = (
        "Solo que me das paz Lo que andaba buscando "
        "Que esa felicidad Que ese que ande sonriendo"
    )
    heard = words_from(
        " ".join(
            [heard_verse, misheard, misheard, "Damas con fama camar tag damas"]
            + [heard_verse, *chorus, *chorus]
        )
    )

    result = align_lyrics(lines, heard)  # difflib: 42%, rejected

    assert result.report.match_ratio > 0.8
    starts = [line.start_ms for line in result.lines]
    assert starts == sorted(starts)
    # The bridge keeps its own place: after both misheard choruses.
    assert result.lines[10].start_ms == heard[42].start_ms


def test_words_before_the_first_and_after_the_last_anchor() -> None:
    heard = words_from("vida y tiempo", start=5000)

    result = align_lyrics(
        ["Dame de tu vida y tiempo ooh yeah"], heard, min_match_ratio=0.3
    )

    words = result.lines[0].words
    assert words[0].start_ms == 5000 - 3 * FALLBACK_WORD_MS
    assert words[3].start_ms == 5000
    assert words[-1].start_ms >= heard[-1].end_ms


def test_missing_words_at_the_song_start_are_squeezed_before_the_first_anchor() -> None:
    heard = words_from("vida", start=20)

    result = align_lyrics(["Dame de tu vida"], heard, min_match_ratio=0.2)

    flat = result.lines[0].words
    assert flat[0].start_ms >= 0
    assert all(w.end_ms > w.start_ms for w in flat)
    for previous, current in zip(flat, flat[1:], strict=False):
        assert current.start_ms >= previous.end_ms


def test_many_missing_words_between_adjacent_anchors_still_get_valid_times() -> None:
    heard = words_from("uno dos", step=15)  # anchors with no gap and tiny spans
    lines = ["uno a b c d e f g h dos"]

    result = align_lyrics(lines, heard, min_match_ratio=0.2)

    flat = result.lines[0].words
    assert len(flat) == 10
    assert all(w.end_ms - w.start_ms >= MIN_ALIGNED_WORD_MS for w in flat)
    for previous, current in zip(flat, flat[1:], strict=False):
        assert current.start_ms >= previous.end_ms


def test_too_many_misheard_words_for_their_span_are_interpolated() -> None:
    heard = words_from("hola XY chau", step=300)
    heard[1] = TranscribedWord(text="XY", start_ms=300, end_ms=310)
    heard[2] = TranscribedWord(text="chau", start_ms=310, end_ms=600)

    result = align_lyrics(["hola a b c d chau"], heard, min_match_ratio=0.3)

    flat = result.lines[0].words
    assert [w.text for w in flat] == ["hola", "a", "b", "c", "d", "chau"]
    assert result.report.interpolated_words == 4


def test_punctuation_only_tokens_are_attached_to_a_word() -> None:
    result = align_lyrics(["— Dame - de tu vida !"], words_from("dame de tu vida"))

    # Leading punctuation goes to the next word, any other to the previous one.
    assert [w.text for w in result.lines[0].words] == ["—Dame-", "de", "tu", "vida!"]


@pytest.mark.parametrize(
    ("lines", "heard"),
    [
        ([], "dame de tu vida"),
        (["Dame de tu vida"], ""),
        (["[Coro x2]"], "dame"),
    ],
)
def test_nothing_to_align_raises(lines: list[str], heard: str) -> None:
    with pytest.raises(LyricsMismatchError):
        align_lyrics(parse_lyrics_text("\n".join(lines)), words_from(heard))


def test_lyrics_of_another_song_are_rejected() -> None:
    with pytest.raises(LyricsMismatchError, match="incomplete, abbreviated"):
        align_lyrics(
            ["Que se apague el día si me mientes"],
            words_from("dame de tu vida y de tu tiempo"),
        )


@pytest.mark.parametrize("seed", range(25))
def test_random_alignment_keeps_every_invariant(seed: int) -> None:
    rng = random.Random(seed)
    vocabulary = ["la", "noche", "vida", "tiempo", "voz", "mar", "sol", "luz"]
    official = [
        " ".join(rng.choice(vocabulary) for _ in range(rng.randint(1, 8)))
        for _ in range(rng.randint(1, 12))
    ]
    tokens = " ".join(official).split()
    heard_tokens = (
        [
            rng.choice(vocabulary) if rng.random() < 0.15 else token
            for token in tokens
            if rng.random() > 0.15  # drop some words
        ]
        or tokens[:1]
    )
    heard = _random_words(rng, len(heard_tokens))
    heard = [
        TranscribedWord(text=text, start_ms=w.start_ms, end_ms=w.end_ms)
        for text, w in zip(heard_tokens, heard, strict=True)
    ]

    try:
        result = align_lyrics(official, heard, min_match_ratio=0.0)
    except LyricsMismatchError:
        return

    assert [line.text for line in result.lines] == official
    SongAnalysisData(
        duration_ms=result.lines[-1].end_ms,
        pipeline=PipelineInfo(separator="s", transcriber="t", pitch_extractor="p"),
        lines=result.lines,
        pitch=PitchCurve(hop_ms=10, midi=[], confidence=[]),
    )
