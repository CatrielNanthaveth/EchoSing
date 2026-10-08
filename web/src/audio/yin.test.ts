import { describe, expect, it } from "vitest";

import { Yin } from "./yin";

const RATE = 48_000;
const SIZE = 2048;

function tone(
  hz: number,
  {
    harmonics = [1],
    noise = 0,
    phase = 0,
  }: { harmonics?: number[]; noise?: number; phase?: number } = {},
): Float32Array {
  let seed = 1;
  const random = () => {
    seed = (seed * 16_807) % 2_147_483_647;
    return seed / 2_147_483_647 - 0.5;
  };
  return Float32Array.from({ length: SIZE }, (_, i) => {
    const t = i / RATE;
    const voiced = harmonics.reduce(
      (sum, amplitude, k) =>
        sum + amplitude * Math.sin(2 * Math.PI * hz * (k + 1) * t + phase),
      0,
    );
    return 0.3 * voiced + noise * random();
  });
}

function cents(actual: number, expected: number): number {
  return 1200 * Math.log2(actual / expected);
}

describe("Yin", () => {
  const yin = new Yin(RATE, SIZE);

  it.each([82.41, 110, 146.83, 220, 261.63, 440, 659.25, 880])(
    "finds a %f Hz sine within 5 cents",
    (hz) => {
      const { f0, clarity } = yin.estimate(tone(hz));

      expect(Math.abs(cents(f0, hz))).toBeLessThan(5);
      expect(clarity).toBeGreaterThan(0.9);
    },
  );

  it("finds the fundamental of a voice-like tone, not a harmonic", () => {
    // Weak fundamental, strong 2nd and 3rd harmonics: a classic octave trap.
    const { f0 } = yin.estimate(tone(196, { harmonics: [0.4, 1, 0.8, 0.3] }));

    expect(Math.abs(cents(f0, 196))).toBeLessThan(10);
  });

  it("tolerates some noise", () => {
    const { f0 } = yin.estimate(tone(220, { noise: 0.1 }));

    expect(Math.abs(cents(f0, 220))).toBeLessThan(10);
  });

  it("does not depend on the phase", () => {
    for (const phase of [0, 1, 2.5]) {
      expect(Math.abs(cents(yin.estimate(tone(330, { phase })).f0, 330))).toBeLessThan(
        5,
      );
    }
  });

  it("reports silence and noise as unvoiced", () => {
    expect(yin.estimate(new Float32Array(SIZE))).toEqual({ f0: 0, clarity: 0 });
    expect(yin.estimate(tone(0, { harmonics: [], noise: 1 })).f0).toBe(0);
  });

  it("ignores pitches outside the search range", () => {
    const narrow = new Yin(RATE, SIZE, { minHz: 150, maxHz: 500 });

    expect(narrow.estimate(tone(80)).f0).not.toBeCloseTo(80, 0);
    expect(narrow.estimate(tone(300)).f0).toBeCloseTo(300, 0);
  });
});
