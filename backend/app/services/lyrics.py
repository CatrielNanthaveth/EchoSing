"""Pure functions that turn timed words into lyric lines.

Segmentation here is the fallback used when no official lyrics are available:
it relies on cues Whisper leaves in sung transcriptions (a capital letter at the
start of each verse, sentence punctuation) and on long pauses, then enforces
line length limits suited to per-line scoring.
"""

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
