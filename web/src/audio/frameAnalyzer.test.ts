import { describe, expect, it } from "vitest";

import { FrameAnalyzer, type VoiceFrame } from "./frameAnalyzer";

const RATE = 1000; // 1 sample = 1 ms keeps the arithmetic readable

function analyze(samples: Float32Array, blockSize = 128, windowSize = 64, hop = 16) {
  const frames: VoiceFrame[] = [];
  const analyzer = new FrameAnalyzer(RATE, (frame) => frames.push(frame), {
    windowSize,
    hopSize: hop,
    highPassHz: null, // a 1 kHz toy rate: test the slicing alone
  });
  for (let start = 0; start < samples.length; start += blockSize) {
    analyzer.push(samples.subarray(start, start + blockSize), start);
  }
  return frames;
}

describe("FrameAnalyzer", () => {
  it("emits a frame per hop once the window is full, timed at its center", () => {
    const frames = analyze(new Float32Array(128), 128);

    // Windows end at samples 64, 80, ..., 128.
    expect(frames.map((frame) => frame.time * RATE)).toEqual([32, 48, 64, 80, 96]);
  });

  it("does not depend on the block size", () => {
    const samples = Float32Array.from({ length: 300 }, (_, i) => Math.sin(i / 3));

    const reference = analyze(samples, 128);
    for (const blockSize of [1, 7, 16, 100]) {
      const frames = analyze(samples, blockSize);
      expect(frames.map((f) => f.time)).toEqual(reference.map((f) => f.time));
      frames.forEach((frame, i) => {
        expect(frame.rms).toBeCloseTo(reference[i]?.rms ?? NaN, 6);
      });
    }
  });

  it("measures the level of the central hop only", () => {
    // Silence, then a 0.5 square wave starting at sample 100.
    const samples = Float32Array.from({ length: 200 }, (_, i) =>
      i >= 100 ? (i % 2 ? 0.5 : -0.5) : 0,
    );

    const frames = analyze(samples);
    const levelAt = (centerMs: number) =>
      frames.find((frame) => frame.time * RATE === centerMs)?.rms;

    // Central hop of the window centered at t covers [t - 8, t + 8).
    expect(levelAt(80)).toBe(0); // the onset is in the window, not its center
    expect(levelAt(96)).toBeCloseTo(0.25); // half the hop is sound
    expect(levelAt(112)).toBeCloseTo(0.5);
  });
});

describe("FrameAnalyzer pitch", () => {
  it("detects the pitch of each frame and skips silence", () => {
    const rate = 48_000;
    const samples = Float32Array.from({ length: rate / 2 }, (_, i) =>
      i < rate / 4 ? 0 : 0.3 * Math.sin((2 * Math.PI * 220 * i) / rate),
    );
    const frames: VoiceFrame[] = [];
    const analyzer = new FrameAnalyzer(rate, (frame) => frames.push(frame));
    for (let start = 0; start < samples.length; start += 128) {
      analyzer.push(samples.subarray(start, start + 128), start);
    }

    const silent = frames.filter((frame) => frame.time < 0.2);
    const sung = frames.filter((frame) => frame.time > 0.3);
    expect(silent.every((frame) => frame.f0 === 0 && frame.clarity === 0)).toBe(true);
    expect(silent.every((frame) => frame.gated && frame.windowRms === 0)).toBe(true);
    expect(sung.every((frame) => Math.abs(frame.f0 - 220) < 1)).toBe(true);
    expect(sung.every((frame) => !frame.gated)).toBe(true);
    expect(sung[0]?.windowRms).toBeCloseTo(0.3 / Math.SQRT2, 2);
  });
});

describe("FrameAnalyzer high-pass filter", () => {
  const rate = 48_000;

  /** A 220 Hz voice on top of strong low-frequency rumble, analyzed. */
  function analyze(highPassHz: number | null, diagnostics = false) {
    const samples = Float32Array.from({ length: rate / 2 }, (_, i) => {
      const t = i / rate;
      return (
        0.1 * Math.sin(2 * Math.PI * 220 * t) + 0.6 * Math.sin(2 * Math.PI * 12 * t)
      );
    });
    const frames: VoiceFrame[] = [];
    const analyzer = new FrameAnalyzer(rate, (frame) => frames.push(frame), {
      highPassHz,
    });
    analyzer.setDiagnostics(diagnostics);
    for (let start = 0; start < samples.length; start += 128) {
      analyzer.push(samples.subarray(start, start + 128), start);
    }
    return frames.filter((frame) => frame.time > 0.15); // filter settled
  }

  it("finds the voice under low-frequency rumble", () => {
    const filtered = analyze(60);
    const unfiltered = analyze(null);

    const voiced = (frames: VoiceFrame[]) =>
      frames.filter((frame) => Math.abs(frame.f0 - 220) < 2).length / frames.length;
    expect(voiced(filtered)).toBe(1);
    expect(voiced(unfiltered)).toBeLessThan(0.5);
  });

  it("reports what the filter removed when diagnosing", () => {
    const frames = analyze(60, true);

    const diagnostics = frames.map((frame) => frame.diagnostics);
    expect(diagnostics.every((d) => d !== undefined)).toBe(true);
    const first = diagnostics[0];
    expect(first?.lowFrequencyShare).toBeGreaterThan(0.9);
    expect(first?.crest).toBeGreaterThan(1);
    expect(analyze(60)[0]?.diagnostics).toBeUndefined();
  });

  it("spots clicks", () => {
    const samples = Float32Array.from({ length: rate / 4 }, (_, i) =>
      i % 4800 === 0 ? 0.9 : 0.05 * Math.sin((2 * Math.PI * 220 * i) / rate),
    );
    const frames: VoiceFrame[] = [];
    const analyzer = new FrameAnalyzer(rate, (frame) => frames.push(frame));
    analyzer.setDiagnostics(true);
    for (let start = 0; start < samples.length; start += 128) {
      analyzer.push(samples.subarray(start, start + 128), start);
    }

    const crests = frames.map((frame) => frame.diagnostics?.crest ?? 0);
    expect(Math.max(...crests)).toBeGreaterThan(10);
    expect(Math.min(...crests)).toBeLessThan(2);
  });
});
