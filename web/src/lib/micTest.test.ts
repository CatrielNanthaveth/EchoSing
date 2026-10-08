import { describe, expect, it } from "vitest";

import type { VoiceFrame } from "../audio/frameAnalyzer";
import { micTestAdvice, micTestStats } from "./micTest";

const HOP_S = 0.01;

function frame(i: number, kind: "voiced" | "gated" | "rejected"): VoiceFrame {
  return {
    time: i * HOP_S,
    rms: 0.05,
    f0: kind === "voiced" ? 220 : 0,
    clarity: kind === "voiced" ? 0.95 : kind === "rejected" ? 0.7 : 0,
    windowRms: kind === "gated" ? 0.001 : 0.1,
    gated: kind === "gated",
  };
}

/** 40 voiced, 10 gated, 10 voiced, 20 rejected, 20 voiced. */
const FRAMES: VoiceFrame[] = [
  ...Array.from({ length: 40 }, () => "voiced" as const),
  ...Array.from({ length: 10 }, () => "gated" as const),
  ...Array.from({ length: 10 }, () => "voiced" as const),
  ...Array.from({ length: 20 }, () => "rejected" as const),
  ...Array.from({ length: 20 }, () => "voiced" as const),
].map((kind, i) => frame(i, kind));

describe("micTestStats", () => {
  it("tells voiced, too quiet and rejected frames apart", () => {
    const stats = micTestStats(FRAMES);

    expect(stats).toMatchObject({
      frames: 100,
      voicedShare: 0.7,
      gatedShare: 0.1,
      rejectedShare: 0.2,
      medianLevelDb: -20,
      gateDb: -46,
      voicedClarity: 0.95,
      rejectedClarity: 0.7,
      clarityThreshold: 0.85,
      medianVoicedRunMs: 200,
      medianF0: 220,
      rawVoicedShare: null,
      lowFrequencyShare: null,
      clickShare: null,
    });
  });

  it("compares with the unfiltered signal when diagnosing", () => {
    const diagnosed = FRAMES.map((f, i) => ({
      ...f,
      diagnostics: {
        rawF0: i < 30 ? 220 : 0,
        rawClarity: 0.5,
        lowFrequencyShare: f.gated ? 0 : 0.8,
        crest: i % 10 === 0 ? 20 : 3,
      },
    }));

    const stats = micTestStats(diagnosed);

    expect(stats).toMatchObject({
      rawVoicedShare: 0.3,
      lowFrequencyShare: 0.8,
      clickShare: 0.1,
    });
    expect(micTestAdvice(stats)).toEqual([
      "Solo se detectó tu voz en el 70% del tiempo.",
      expect.stringContaining("clics"),
      "El filtro de graves recupera el 40% de tu voz (el micrófono capta mucho grave de cerca).",
      expect.stringContaining("Hay volumen pero"),
    ]);
  });

  it("handles no audio", () => {
    expect(micTestStats([])).toMatchObject({
      frames: 0,
      voicedShare: 0,
      medianLevelDb: null,
      voicedClarity: null,
      medianVoicedRunMs: null,
    });
  });
});

describe("micTestAdvice", () => {
  it("explains what is wrong", () => {
    expect(micTestAdvice(micTestStats(FRAMES))).toEqual([
      "Solo se detectó tu voz en el 70% del tiempo.",
      expect.stringContaining("Hay volumen pero"),
    ]);

    const quiet = FRAMES.map((f, i) => (i % 3 === 0 ? frame(i, "gated") : f));
    expect(micTestAdvice(micTestStats(quiet))).toContainEqual(
      expect.stringContaining("te capta bajo"),
    );
  });

  it("is happy with a clean voice", () => {
    const clean = FRAMES.map((_, i) => frame(i, "voiced"));

    expect(micTestAdvice(micTestStats(clean))).toEqual(["Tu voz se detecta bien."]);
  });

  it("reports missing audio", () => {
    expect(micTestAdvice(micTestStats([]))).toEqual(["No llegó audio del micrófono."]);
  });
});
