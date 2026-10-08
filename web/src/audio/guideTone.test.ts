import { describe, expect, it, vi } from "vitest";

import type { PitchResponse } from "../api/types";
import { GUIDE_GAIN, playGuide } from "./guideTone";

function fakeParam() {
  return {
    value: 0,
    setValueAtTime: vi.fn<(value: number, time: number) => void>(),
    setTargetAtTime: vi.fn<(value: number, time: number, constant: number) => void>(),
  };
}

function fakeContext() {
  const oscillator = {
    type: "sine",
    frequency: fakeParam(),
    connect: vi.fn((node: unknown) => node),
    disconnect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
  };
  const gain = { gain: fakeParam(), connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    destination: {},
    createOscillator: () => oscillator,
    createGain: () => gain,
  };
  return { context: context as unknown as BaseAudioContext, oscillator, gain };
}

const REFERENCE: PitchResponse = {
  analysis_id: "a",
  line_index: 0,
  start_ms: 5000,
  hop_ms: 10,
  // A4 for 3 frames, a gap, then A#4 and a tiny wobble (ignored).
  midi: [69, 69, 69, null, 70, 70.01],
  confidence: [90, 90, 90, 0, 90, 90],
};

describe("playGuide", () => {
  it("follows the melody in sync and is silent where nobody sings", () => {
    const { context, oscillator, gain } = fakeContext();

    playGuide(context, REFERENCE, 10);

    expect(oscillator.type).toBe("triangle");
    expect(oscillator.frequency.setValueAtTime.mock.calls).toEqual([
      [440, 10],
      [expect.closeTo(466.16, 1), expect.closeTo(10.04, 5)],
    ]);
    expect(oscillator.frequency.setTargetAtTime).not.toHaveBeenCalled();
    expect(
      gain.gain.setTargetAtTime.mock.calls.map(([value, time]) => [value, time]),
    ).toEqual([
      [GUIDE_GAIN, 10],
      [0, expect.closeTo(10.03, 5)],
      [GUIDE_GAIN, expect.closeTo(10.04, 5)],
      [0, expect.closeTo(10.06, 5)], // end of the line
    ]);
    expect(oscillator.start).toHaveBeenCalledWith(10);
    expect(oscillator.stop).toHaveBeenCalledWith(expect.closeTo(10.26, 5));
  });

  it("glides between notes sung without a gap", () => {
    const { context, oscillator } = fakeContext();

    playGuide(context, { ...REFERENCE, midi: [69, 71], confidence: [90, 90] }, 0);

    expect(oscillator.frequency.setTargetAtTime).toHaveBeenCalledWith(
      expect.closeTo(493.88, 1),
      0.01,
      expect.any(Number),
    );
  });

  it("stops once, even if it already ended", () => {
    const { context, oscillator, gain } = fakeContext();
    const stop = playGuide(context, REFERENCE, 0);
    oscillator.stop.mockImplementation(() => {
      throw new DOMException("already stopped", "InvalidStateError");
    });

    stop();
    stop();

    expect(oscillator.disconnect).toHaveBeenCalledOnce();
    expect(gain.disconnect).toHaveBeenCalledOnce();
  });
});
