import { describe, expect, it } from "vitest";

import type { VoiceFrame } from "../audio/frameAnalyzer";
import { detectOnsets, measureLatency } from "./detect";

const HOP_S = 0.01;
const BEEPS = Array.from({ length: 8 }, (_, i) => 1 + i * 0.6);

/** Background noise with short bursts (claps) at the given times. */
function recording(
  claps: readonly number[],
  durationS = 6,
  noise = 0.002,
): VoiceFrame[] {
  const frames: VoiceFrame[] = [];
  for (let i = 0; i * HOP_S < durationS; i++) {
    const time = i * HOP_S;
    const clap = claps.some((start) => time >= start && time < start + 0.05);
    frames.push({
      time,
      rms: clap ? 0.3 : noise * (1 + (i % 3) / 2),
      f0: 0,
      clarity: 0,
    });
  }
  return frames;
}

describe("detectOnsets", () => {
  it("finds the start of each burst once", () => {
    const onsets = detectOnsets(recording([1.2, 2.5]));

    expect(onsets.map((t) => Math.round(t * 100) / 100)).toEqual([1.2, 2.5]);
  });

  it("ignores a burst right after another (ringing)", () => {
    expect(detectOnsets(recording([1, 1.1]))).toHaveLength(1);
  });

  it("finds nothing in silence or without frames", () => {
    expect(detectOnsets(recording([]))).toEqual([]);
    expect(detectOnsets([])).toEqual([]);
  });
});

describe("measureLatency", () => {
  it("measures the delay between beeps and claps", () => {
    const result = measureLatency(recording(BEEPS.map((beep) => beep + 0.15)), BEEPS);

    expect(result).toEqual({ ok: true, latencyMs: 150, matched: 8, spreadMs: 0 });
  });

  it("uses the median and drops outliers", () => {
    const jitter = [0.14, 0.16, 0.15, 0.13, 0.17, 0.15, 0.4, 0.15];
    const result = measureLatency(
      recording(BEEPS.map((beep, i) => beep + (jitter[i] ?? 0))),
      BEEPS,
    );

    expect(result).toMatchObject({ ok: true, latencyMs: 150, matched: 7 });
    expect(result.ok && result.spreadMs).toBe(10);
  });

  it("accepts claps slightly ahead of the beep", () => {
    const result = measureLatency(recording(BEEPS.map((beep) => beep - 0.05)), BEEPS);

    expect(result).toMatchObject({ ok: true, latencyMs: -50 });
  });

  it("fails without enough claps", () => {
    const result = measureLatency(
      recording(BEEPS.slice(0, 4).map((b) => b + 0.1)),
      BEEPS,
    );

    expect(result).toEqual({ ok: false, reason: "no_signal", matched: 4 });
  });

  it("fails when the claps are all over the place", () => {
    const offsets = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.05, 0.25];
    const result = measureLatency(
      recording(BEEPS.map((beep, i) => beep + (offsets[i] ?? 0))),
      BEEPS,
    );

    expect(result).toMatchObject({ ok: false, reason: "inconsistent" });
  });
});
