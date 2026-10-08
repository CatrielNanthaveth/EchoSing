import type { LyricLine, SongDetail, SongPage, SongSummary } from "../api/types";

export function songSummary(overrides: Partial<SongSummary> = {}): SongSummary {
  return {
    id: "song-1",
    title: "Chachacha",
    artist: "Josean Log",
    language: "es",
    duration_ms: 215_000,
    line_count: 37,
    reprocessing: false,
    ...overrides,
  };
}

export function songPage(
  items: SongSummary[],
  overrides: Partial<SongPage> = {},
): SongPage {
  return { items, total: items.length, limit: 20, offset: 0, ...overrides };
}

/** A line whose words split its time evenly. */
export function lyricLine(
  index: number,
  startMs: number,
  endMs: number,
  text: string,
): LyricLine {
  const words = text.split(" ");
  const step = (endMs - startMs) / words.length;
  return {
    index,
    start_ms: startMs,
    end_ms: endMs,
    text,
    words: words.map((word, i) => ({
      text: word,
      start_ms: Math.round(startMs + i * step),
      end_ms: Math.round(startMs + (i + 1) * step),
    })),
  };
}

export function songDetail(overrides: Partial<SongDetail> = {}): SongDetail {
  const lines = [
    lyricLine(0, 5000, 7000, "Hola mundo"),
    lyricLine(1, 8000, 10000, "Segunda línea"),
    lyricLine(2, 10000, 12000, "Tercera línea"),
  ];
  return {
    id: "song-1",
    title: "Chachacha",
    artist: "Josean Log",
    language: "es",
    duration_ms: 60_000,
    line_count: lines.length,
    reprocessing: false,
    analysis_id: "analysis-1",
    analysis_version: 1,
    lines,
    ...overrides,
  };
}
