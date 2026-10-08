import { describe, expect, it } from "vitest";

import { formatDuration } from "./format";

describe("formatDuration", () => {
  it.each([
    [0, "0:00"],
    [9_400, "0:09"],
    [59_600, "1:00"],
    [215_000, "3:35"],
    [3_725_000, "62:05"],
  ])("formats %d ms as %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });

  it.each([null, undefined, -1, Number.NaN])("shows a dash for %s", (ms) => {
    expect(formatDuration(ms)).toBe("–");
  });
});
