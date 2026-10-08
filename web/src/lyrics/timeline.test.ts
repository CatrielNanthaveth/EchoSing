import { describe, expect, it } from "vitest";

import { lyricLine } from "../test/factories";
import { lineAt, lyricsPosition, nextLineAt, startedWords } from "./timeline";

const LAST = lyricLine(2, 6000, 9000, "cuatro cinco seis");
const LINES = [
  lyricLine(0, 1000, 3000, "uno dos"),
  lyricLine(1, 3000, 4000, "tres"),
  LAST,
];

describe("lineAt", () => {
  it.each([
    [0, -1],
    [999, -1],
    [1000, 0],
    [2999, 0],
    [3000, 1], // back-to-back lines: the next one wins at the boundary
    [4000, -1],
    [5999, -1],
    [6000, 2],
    [9000, -1],
  ])("at %d ms is line %d", (timeMs, expected) => {
    expect(lineAt(LINES, timeMs)).toBe(expected);
  });

  it("handles no lines", () => {
    expect(lineAt([], 0)).toBe(-1);
  });
});

describe("nextLineAt", () => {
  it.each([
    [0, 0],
    [1000, 1],
    [4500, 2],
    [6000, -1],
  ])("after %d ms is line %d", (timeMs, expected) => {
    expect(nextLineAt(LINES, timeMs)).toBe(expected);
  });
});

describe("startedWords", () => {
  it.each([
    [5999, 0],
    [6000, 1],
    [7000, 2],
    [8999, 3],
  ])("at %d ms", (timeMs, expected) => {
    expect(startedWords(LAST, timeMs)).toBe(expected);
  });
});

describe("lyricsPosition", () => {
  it("follows the line being sung", () => {
    expect(lyricsPosition(LINES, 2000)).toEqual({
      line: 0,
      active: true,
      words: 2,
      countdown: 0,
    });
  });

  it("counts down to the next line between lines", () => {
    expect(lyricsPosition(LINES, 4100)).toEqual({
      line: 2,
      active: false,
      words: 0,
      countdown: 2,
    });
  });

  it("ends after the last line", () => {
    expect(lyricsPosition(LINES, 9500)).toEqual({
      line: -1,
      active: false,
      words: 0,
      countdown: 0,
    });
  });
});
