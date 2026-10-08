import { describe, expect, it } from "vitest";

import { HighPass } from "./highPass";

const RATE = 48_000;

/** RMS gain of the filter on a sine, after it settles. */
function gain(hz: number, offset = 0): number {
  const filter = new HighPass(RATE);
  const samples = RATE; // 1 s
  let input = 0;
  let output = 0;
  for (let i = 0; i < samples; i++) {
    const x = Math.sin((2 * Math.PI * hz * i) / RATE) + offset;
    const y = filter.next(x);
    if (i >= samples / 2) {
      input += (x - offset) ** 2;
      output += y * y;
    }
  }
  return Math.sqrt(output / input);
}

describe("HighPass", () => {
  it("removes DC", () => {
    const filter = new HighPass(RATE);
    let last = 1;
    for (let i = 0; i < RATE; i++) last = filter.next(1);

    expect(Math.abs(last)).toBeLessThan(1e-3);
  });

  it("attenuates rumble and keeps the voice", () => {
    expect(gain(15)).toBeLessThan(0.07); // ~-24 dB
    expect(gain(60)).toBeCloseTo(Math.SQRT1_2, 2); // -3 dB at the cutoff
    expect(gain(110)).toBeGreaterThan(0.95); // low male voice
    expect(gain(440)).toBeGreaterThan(0.999);
  });

  it("passes the voice even on top of an offset", () => {
    expect(gain(220, 0.5)).toBeGreaterThan(0.99);
  });
});
