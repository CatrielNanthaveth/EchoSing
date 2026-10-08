"""Pure functions that turn timed words into lyric lines.

Two strategies:

- ``align_lyrics``: official lyrics provide the text and the line breaks; the
  transcription only provides timings. This is the preferred path.
- ``segment_lines``: fallback when no official lyrics are available. It relies
  on cues Whisper leaves in sung transcriptions (a capital letter at the start
  of each verse, sentence punctuation) and on long pauses, then enforces line
  length limits suited to per-line scoring.
"""

import difflib
import re
import unicodedata
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.ml.transcription import TranscribedWord
from app.schemas.analysis import LyricLine, Word

SENTENCE_END = (".", "?", "!", "…")
CLAUSE_END = (",", ";", ":")
LINE_OPENERS = ("¿", "¡")

# Words that almost never end a lyric line: a capitalized word right after
# one of them is most likely a proper noun ("un Peter Pan"), not a new verse.
NON_FINAL_WORDS = frozenset(
    {
        # Spanish
        "a", "al", "con", "de", "del", "el", "en", "la", "las", "lo", "los",
        "mi", "mis", "o", "para", "por", "que", "su", "sus", "tu", "tus",
        "u", "un", "una", "unas", "unos", "y",
        # English
        "an", "and", "of", "on", "or", "the", "to", "for", "in", "my", "your",
    }
)  # fmt: skip

# Common words that often open a verse. Unlike proper nouns, a capitalized
# one starts a new line even right after another capitalized word
# ("Peter Pan | Que ha jugado...").
VERSE_STARTERS = NON_FINAL_WORDS | frozenset(
    {
        # Spanish
        "aunque", "como", "cuando", "desde", "donde", "es", "hasta", "me",
        "ni", "no", "pero", "porque", "se", "si", "sin", "solo", "te", "yo",
        # English
        "but", "i", "if", "it", "so", "when", "you",
    }
)  # fmt: skip


class SegmentationConfig(BaseModel):
    """Thresholds of the line segmentation heuristics.

    Attributes:
        pause_split_ms: A silence at least this long always ends a line.
        max_line_ms: Lines longer than this are split.
        max_line_words: Lines with more words than this are split.
        min_line_ms: Lines shorter than this are merged into a neighbor.
        min_line_words: Lines with fewer words than this are merged.
    """

    model_config = ConfigDict(frozen=True)

    pause_split_ms: int = Field(default=1000, gt=0)
    max_line_ms: int = Field(default=8000, gt=0)
    max_line_words: int = Field(default=14, ge=2)
    min_line_ms: int = Field(default=800, ge=0)
    min_line_words: int = Field(default=2, ge=1)


Chunk = list[TranscribedWord]


def segment_lines(
    words: Sequence[TranscribedWord], config: SegmentationConfig | None = None
) -> list[LyricLine]:
    """Group timed words into lyric lines.

    Steps: split at verse cues (capitalized word, sentence end, ``¿``/``¡``,
    long pause), split lines that are too long (preferring a comma, then the
    largest pause, then the middle) and merge lines that are too short into the
    closest neighbor when the result still fits the limits.

    Args:
        words: Words in lyric order, with strictly increasing times.
        config: Thresholds; defaults are tuned for sung lyrics.

    Returns:
        Lines indexed from 0, covering every word exactly once and in order.
    """
    settings = config or SegmentationConfig()
    chunks = _split_at_cues(list(words), settings)
    chunks = [part for chunk in chunks for part in _split_long(chunk, settings)]
    chunks = _merge_short(chunks, settings)
    return [_to_line(index, chunk) for index, chunk in enumerate(chunks)]


def _gap(previous: TranscribedWord, current: TranscribedWord) -> int:
    return current.start_ms - previous.end_ms


def _duration(chunk: Chunk) -> int:
    return chunk[-1].end_ms - chunk[0].start_ms


def _starts_uppercase(text: str) -> bool:
    first_letter = next((char for char in text if char.isalpha()), "")
    return first_letter.isupper()


def _bare(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def _starts_verse(previous: TranscribedWord, current: TranscribedWord) -> bool:
    """Whether ``current`` looks like the first word of a new verse."""
    if current.text.startswith(LINE_OPENERS):
        return True
    if not _starts_uppercase(current.text):
        return False
    previous_is_bare = not previous.text.endswith(SENTENCE_END + CLAUSE_END)
    # "Peter Pan": consecutive capitalized words form a proper noun, unless the
    # current one is a common verse opener ("Peter Pan | Que ...").
    if (
        _starts_uppercase(previous.text)
        and previous_is_bare
        and _bare(current.text) not in VERSE_STARTERS
    ):
        return False
    # "un Peter Pan": articles and prepositions do not end lines.
    return not (previous_is_bare and _bare(previous.text) in NON_FINAL_WORDS)


def _split_at_cues(words: Chunk, config: SegmentationConfig) -> list[Chunk]:
    if not words:
        return []
    chunks: list[Chunk] = [[words[0]]]
    for previous, current in zip(words, words[1:], strict=False):
        if (
            _gap(previous, current) >= config.pause_split_ms
            or previous.text.endswith(SENTENCE_END)
            or _starts_verse(previous, current)
        ):
            chunks.append([current])
        else:
            chunks[-1].append(current)
    return chunks


def _fits(chunk: Chunk, config: SegmentationConfig) -> bool:
    return len(chunk) == 1 or (
        _duration(chunk) <= config.max_line_ms and len(chunk) <= config.max_line_words
    )


def _split_long(chunk: Chunk, config: SegmentationConfig) -> list[Chunk]:
    """Recursively split ``chunk`` until every part fits the limits."""
    if _fits(chunk, config):
        return [chunk]
    candidates = range(1, len(chunk))
    # Avoid leaving tiny fragments when a balanced split is possible.
    balanced = [
        k for k in candidates if min(k, len(chunk) - k) >= config.min_line_words
    ] or list(candidates)
    middle = len(chunk) / 2

    def score(k: int) -> tuple[bool, bool, int, float]:
        last_word = chunk[k - 1].text
        after_clause = last_word.endswith(CLAUSE_END)
        # Never prefer ending a line on "para", "the"... when avoidable.
        ends_naturally = _bare(last_word) not in NON_FINAL_WORDS
        return (
            after_clause,
            ends_naturally,
            _gap(chunk[k - 1], chunk[k]),
            -abs(k - middle),
        )

    best = max(balanced, key=score)
    return _split_long(chunk[:best], config) + _split_long(chunk[best:], config)


def _is_short(chunk: Chunk, config: SegmentationConfig) -> bool:
    return len(chunk) < config.min_line_words or _duration(chunk) < config.min_line_ms


def _merge_short(chunks: list[Chunk], config: SegmentationConfig) -> list[Chunk]:
    """Merge short lines into their closest neighbor while the result fits."""
    merged = [list(chunk) for chunk in chunks]
    index = 0
    while index < len(merged):
        chunk = merged[index]
        if not _is_short(chunk, config):
            index += 1
            continue
        options: list[tuple[int, int]] = []  # (gap to neighbor, neighbor index)
        if index > 0:
            options.append((_gap(merged[index - 1][-1], chunk[0]), index - 1))
        if index + 1 < len(merged):
            options.append((_gap(chunk[-1], merged[index + 1][0]), index + 1))
        for _, neighbor in sorted(options):
            first, second = sorted((index, neighbor))
            candidate = merged[first] + merged[second]
            if (
                _fits(candidate, config)
                and _gap(merged[first][-1], merged[second][0]) < config.pause_split_ms
            ):
                merged[first : second + 1] = [candidate]
                index = max(first - 1, 0)  # the merged line may still be short
                break
        else:
            index += 1
    return merged


def _to_line(index: int, chunk: Chunk) -> LyricLine:
    return LyricLine(
        index=index,
        start_ms=chunk[0].start_ms,
        end_ms=chunk[-1].end_ms,
        text=" ".join(word.text for word in chunk),
        words=[
            Word(
                text=word.text,
                start_ms=word.start_ms,
                end_ms=word.end_ms,
                probability=word.probability,
            )
            for word in chunk
        ],
    )


# --- Official lyrics alignment -------------------------------------------------

MIN_ALIGNED_WORD_MS = 10
# Duration assumed for words that must be placed before the first or after the
# last word recognized by the transcriber.
FALLBACK_WORD_MS = 300
MAX_LYRICS_CHARS = 20_000
_SECTION_LABEL = re.compile(r"^\[.*\]$")
_BACKING_VOCALS = re.compile(r"^\(.*\)$")


class LyricsMismatchError(ValueError):
    """The official lyrics do not match the transcribed audio well enough."""


class AlignmentReport(BaseModel):
    """How well the official lyrics matched the transcription.

    Attributes:
        lyric_words: Words in the official lyrics.
        matched_words: Official words found verbatim in the transcription.
        replaced_words: Official words timed from different transcribed words.
        interpolated_words: Official words the transcriber missed, timed by
            interpolation between their neighbors.
        unused_transcribed_words: Transcribed words with no official
            counterpart (ad-libs, backing vocals or hallucinations).
    """

    lyric_words: int
    matched_words: int
    replaced_words: int
    interpolated_words: int
    unused_transcribed_words: int

    @property
    def match_ratio(self) -> float:
        """Fraction of official words found verbatim in the transcription."""
        return self.matched_words / self.lyric_words if self.lyric_words else 0.0


class AlignedLyrics(BaseModel):
    """Official lyrics with word timings.

    Attributes:
        lines: Lines of the official lyrics, with timed words.
        report: Alignment quality metrics.
    """

    lines: list[LyricLine]
    report: AlignmentReport


def parse_lyrics_text(text: str) -> list[str]:
    """Extract the sung lines from lyrics text.

    One verse per line. Empty lines (stanza breaks), section labels such as
    ``[Coro]`` and lines fully in parentheses (backing vocals, rarely captured
    by the transcriber) are skipped. Inner whitespace is collapsed.

    Args:
        text: Lyrics as plain text.

    Returns:
        The lines to display and score, in order.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line and not _SECTION_LABEL.match(line) and not _BACKING_VOCALS.match(line):
            lines.append(line)
    return lines


def normalize_word(text: str) -> str:
    """Comparison key of a word: casefolded, without accents or punctuation.

    Args:
        text: A word as written.

    Returns:
        Its letters and digits only, e.g. ``"Créemelo,"`` -> ``"creemelo"``.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        char
        for char in decomposed
        if char.isalnum() and not unicodedata.combining(char)
    )


def _split_line(line: str) -> list[str]:
    """Split a line into words, attaching punctuation-only tokens to a neighbor."""
    words: list[str] = []
    pending = ""
    for token in line.split():
        if not normalize_word(token):
            if words:
                words[-1] += token
            else:
                pending += token
            continue
        words.append(pending + token)
        pending = ""
    return words


def _distribute(start: int, end: int, weights: Sequence[int]) -> list[tuple[int, int]]:
    """Split ``[start, end)`` into consecutive spans proportional to ``weights``.

    Every span lasts at least ``MIN_ALIGNED_WORD_MS``; the caller guarantees
    ``end - start >= len(weights) * MIN_ALIGNED_WORD_MS``.
    """
    spare = end - start - len(weights) * MIN_ALIGNED_WORD_MS
    total = sum(weights)
    spans: list[tuple[int, int]] = []
    cursor = start
    accumulated = 0
    for index, weight in enumerate(weights):
        accumulated += weight
        # Cumulative rounding keeps the total exact.
        extra = spare * accumulated // total
        span_end = (
            end
            if index == len(weights) - 1
            else start + (index + 1) * MIN_ALIGNED_WORD_MS + extra
        )
        spans.append((cursor, span_end))
        cursor = span_end
    return spans


def align_lyrics(
    lines: Sequence[str],
    transcribed: Sequence[TranscribedWord],
    *,
    min_match_ratio: float = 0.5,
) -> AlignedLyrics:
    """Time the words of official lyrics using a transcription.

    Words are compared by ``normalize_word`` and aligned as sequences, so the
    alignment survives missing, extra and misheard words:

    - matched words take the transcribed timing;
    - misheard words share the time span of the words heard in their place;
    - words the transcriber missed are interpolated between their neighbors
      (borrowing time from them when Whisper left no gap);
    - extra transcribed words are ignored.

    Args:
        lines: Official lyric lines (see ``parse_lyrics_text``).
        transcribed: Transcribed words with strictly increasing times.
        min_match_ratio: Minimum fraction of official words that must be found
            in the transcription.

    Returns:
        The official lines with timed words and a quality report.

    Raises:
        LyricsMismatchError: If there is nothing to align or too few words
            match (lyrics incomplete, abbreviated or from another song).
    """
    official = [(line_index, word) for line_index, line in enumerate(lines)
                for word in _split_line(line)]  # fmt: skip
    if not official:
        raise LyricsMismatchError("The lyrics contain no words")
    if not transcribed:
        raise LyricsMismatchError("The transcription contains no words to align with")

    official_keys = [normalize_word(word) for _, word in official]
    heard_keys = [normalize_word(word.text) for word in transcribed]
    matcher = difflib.SequenceMatcher(None, official_keys, heard_keys, autojunk=False)

    times: list[tuple[int, int] | None] = [None] * len(official)
    matched = replaced = unused = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                heard = transcribed[j1 + offset]
                times[i1 + offset] = (heard.start_ms, heard.end_ms)
            matched += i2 - i1
        elif tag == "replace":
            span_start, span_end = transcribed[j1].start_ms, transcribed[j2 - 1].end_ms
            weights = [max(len(key), 1) for key in official_keys[i1:i2]]
            if span_end - span_start >= len(weights) * MIN_ALIGNED_WORD_MS:
                times[i1:i2] = _distribute(span_start, span_end, weights)
                replaced += i2 - i1
            # else: too many words for the span, interpolate them below.
            unused += max((j2 - j1) - (i2 - i1), 0)
        elif tag == "insert":
            unused += j2 - j1

    report = AlignmentReport(
        lyric_words=len(official),
        matched_words=matched,
        replaced_words=replaced,
        interpolated_words=sum(span is None for span in times),
        unused_transcribed_words=unused,
    )
    if report.match_ratio < min_match_ratio:
        raise LyricsMismatchError(
            f"Only {report.match_ratio:.0%} of the lyrics match the audio "
            f"(minimum {min_match_ratio:.0%}): are they incomplete, abbreviated "
            "(e.g. 'chorus x2') or from another song?"
        )

    resolved = _interpolate_missing(times, official_keys)
    return AlignedLyrics(lines=_build_lines(lines, official, resolved), report=report)


def _interpolate_missing(
    times: list[tuple[int, int] | None], keys: Sequence[str]
) -> list[tuple[int, int]]:
    """Fill the words without timing, keeping times strictly increasing.

    Each run of untimed words is placed in the gap between its timed
    neighbors. When the gap is too small (Whisper usually stretches words up
    to the next one), the window grows outwards to include timed neighbors,
    which are re-timed together with the run. Words before the first or after
    the last timed word get ``FALLBACK_WORD_MS`` each.
    """
    spans = list(times)
    total = len(spans)
    index = 0
    while index < total:
        if spans[index] is not None:
            index += 1
            continue
        low, high = index, index  # window of words to (re)distribute: [low, high)
        while high < total and spans[high] is None:
            high += 1
        while True:
            count = high - low
            after = spans[high] if high < total else None
            before = spans[low - 1] if low > 0 else None
            if before is not None and after is not None:
                start, end = before[1], after[0]
            elif before is not None:  # after the last timed word
                start, end = before[1], before[1] + count * FALLBACK_WORD_MS
            elif after is not None:  # before the first timed word
                start, end = max(after[0] - count * FALLBACK_WORD_MS, 0), after[0]
            else:  # no timed word at all
                start, end = 0, count * FALLBACK_WORD_MS
            if end - start >= count * MIN_ALIGNED_WORD_MS:
                break
            # Not enough room: also re-time the closest timed neighbor.
            if low > 0:
                low -= 1
            else:
                high += 1
        weights = [max(len(key), 1) for key in keys[low:high]]
        spans[low:high] = _distribute(start, end, weights)
        index = high
    return [span for span in spans if span is not None]


def _build_lines(
    lines: Sequence[str],
    official: Sequence[tuple[int, str]],
    spans: Sequence[tuple[int, int]],
) -> list[LyricLine]:
    """Group timed official words back into their lines."""
    words_by_line: list[list[Word]] = [[] for _ in lines]
    for (line_index, text), (start, end) in zip(official, spans, strict=True):
        words_by_line[line_index].append(Word(text=text, start_ms=start, end_ms=end))
    return [
        LyricLine(
            index=index,
            start_ms=words[0].start_ms,
            end_ms=words[-1].end_ms,
            text=" ".join(word.text for word in words),
            words=words,
        )
        for index, words in enumerate(line for line in words_by_line if line)
    ]
