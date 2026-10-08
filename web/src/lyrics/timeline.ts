import type { LyricLine } from "../api/types";

/** Number of items before the first one starting after `timeMs`. */
function countStarted(items: readonly { start_ms: number }[], timeMs: number): number {
  let low = 0;
  let high = items.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if ((items[middle]?.start_ms ?? Infinity) <= timeMs) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** Index of the line being sung at `timeMs`, or -1 between lines. */
export function lineAt(lines: readonly LyricLine[], timeMs: number): number {
  const index = countStarted(lines, timeMs) - 1;
  const line = lines[index];
  return line !== undefined && timeMs < line.end_ms ? index : -1;
}

/** Index of the first line starting after `timeMs`, or -1 if none is left. */
export function nextLineAt(lines: readonly LyricLine[], timeMs: number): number {
  const index = countStarted(lines, timeMs);
  return index < lines.length ? index : -1;
}

/** How many words of the line have started at `timeMs`. */
export function startedWords(line: LyricLine, timeMs: number): number {
  return countStarted(line.words, timeMs);
}

export interface LyricsPosition {
  /** Line on screen: the one being sung, else the next one. -1 at the end. */
  line: number;
  /** Whether `line` is being sung (false while waiting for it). */
  active: boolean;
  /** Words of `line` already started. */
  words: number;
  /** Whole seconds until `line` starts while waiting (0 when active). */
  countdown: number;
}

/** Everything the lyrics view needs at `timeMs`. */
export function lyricsPosition(
  lines: readonly LyricLine[],
  timeMs: number,
): LyricsPosition {
  const current = lineAt(lines, timeMs);
  const currentLine = lines[current];
  if (currentLine !== undefined) {
    return {
      line: current,
      active: true,
      words: startedWords(currentLine, timeMs),
      countdown: 0,
    };
  }
  const next = nextLineAt(lines, timeMs);
  const nextLine = lines[next];
  return {
    line: next,
    active: false,
    words: 0,
    countdown: nextLine ? Math.ceil((nextLine.start_ms - timeMs) / 1000) : 0,
  };
}
