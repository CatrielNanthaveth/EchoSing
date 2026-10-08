import { describe, expect, it } from "vitest";

import { hzToMidi, levelFraction, noteName } from "./pitch";

describe("pitch helpers", () => {
  it("converts Hz to MIDI", () => {
    expect(hzToMidi(440)).toBe(69);
    expect(hzToMidi(220)).toBe(57);
    expect(hzToMidi(261.63)).toBeCloseTo(60, 2);
  });

  it.each([
    [440, "A4"],
    [261.63, "C4"],
    [82.41, "E2"],
    [466.16, "A#4"],
    [452, "A4"], // 47 cents sharp still rounds to A4
  ])("names %f Hz as %s", (hz, name) => {
    expect(noteName(hz)).toBe(name);
  });

  it.each([0, -1, Number.NaN])("has no note for %f Hz", (hz) => {
    expect(noteName(hz)).toBeNull();
  });

  it.each([
    [0, 0],
    [0.001, 0],
    [0.01, 1 / 3],
    [1, 1],
    [2, 1],
  ])("maps RMS %f to level %f", (rms, level) => {
    expect(levelFraction(rms)).toBeCloseTo(level);
  });
});
