import type { SongPage, SongSummary } from "../api/types";

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
