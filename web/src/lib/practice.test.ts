import { describe, expect, it } from "vitest";

import { lineAnalysis, linePractice } from "../test/factories";
import {
  chartRows,
  pitchDomain,
  pitchTicks,
  practiceAdvice,
  wordStats,
} from "./practice";

describe("chartRows", () => {
  it("puts both curves on seconds from the line start", () => {
    const rows = chartRows(lineAnalysis(), false);

    expect(rows).toHaveLength(10);
    expect(rows[1]).toEqual({ timeS: 0.02, reference: 57, voice: 57 });
    expect(rows[9]).toEqual({ timeS: 0.18, reference: null, voice: null });
  });

  it("shows what was sung or what was matched", () => {
    const analysis = lineAnalysis({
      sung_midi: [null, 56, 56, 56, 56, 56, 58, 58, 58, 58],
      aligned_midi: [56, 56, 56, 56, 56, 58, 58, 58, 58, null],
    });

    expect(chartRows(analysis, false)[0]?.voice).toBeNull();
    expect(chartRows(analysis, true)[0]?.voice).toBe(56);
  });
});

describe("pitch axis", () => {
  it("covers both curves with a semitone of margin", () => {
    const rows = chartRows(
      lineAnalysis({
        sung_midi: [55.4, null, null, null, null, null, null, null, null, 60.2],
      }),
      false,
    );

    expect(pitchDomain(rows)).toEqual([54, 62]);
  });

  it("has a default range without voice", () => {
    expect(pitchDomain([{ timeS: 0, reference: null, voice: null }])).toEqual([55, 70]);
  });

  it("puts whole-semitone ticks, at most ~8", () => {
    expect(pitchTicks([56, 60])).toEqual([56, 57, 58, 59, 60]);
    expect(pitchTicks([40, 80])).toEqual([40, 45, 50, 55, 60, 65, 70, 75, 80]);
  });
});

describe("practiceAdvice", () => {
  it("praises a centered, timely line", () => {
    expect(practiceAdvice(lineAnalysis())).toEqual([
      "Afinación centrada en la melodía.",
      "Entraste a tiempo.",
    ]);
  });

  it.each([
    [-0.64, 120, ["Cantaste ~0,6 semitonos más grave.", "Ibas ~120 ms atrasado."]],
    [1.04, -80, ["Cantaste ~1 semitono más agudo.", "Ibas ~80 ms adelantado."]],
  ])("explains a pitch offset of %f and a delay of %f ms", (pitch, timing, advice) => {
    expect(
      practiceAdvice(
        lineAnalysis({ pitch_offset_semitones: pitch, timing_offset_ms: timing }),
      ),
    ).toEqual(advice);
  });

  it.each([
    [-12, "Cantaste una octava más grave"],
    [24, "Cantaste 2 octavas más aguda"],
  ])("mentions an octave shift of %d", (shift, text) => {
    expect(practiceAdvice(lineAnalysis({ octave_shift: shift }))[2]).toContain(text);
  });

  it("explains lines without voice or without melody", () => {
    expect(
      practiceAdvice(
        lineAnalysis({ pitch_offset_semitones: null, timing_offset_ms: null }),
      ),
    ).toEqual(["No se detectó tu voz en este verso."]);
    expect(
      practiceAdvice(
        lineAnalysis({
          result: {
            scorable: false,
            score: null,
            accuracy: null,
            hit: false,
            voiced_frames: 2,
          },
        }),
      ),
    ).toEqual(["Este verso casi no tiene melodía en la original: no puntúa."]);
  });
});

describe("wordStats", () => {
  it("averages each word's frames", () => {
    const analysis = lineAnalysis({
      aligned_midi: [56, 56, 56, 56, 56, 59.5, 59.5, null, null, null],
    });

    expect(wordStats(linePractice().words, analysis)).toEqual([
      { text: "Hola", reference: 57, voice: 56, offset: -1 },
      { text: "mundo", reference: 59, voice: 59.5, offset: 0.5 },
    ]);
  });

  it("has no values where nothing was sung or there is no melody", () => {
    const analysis = lineAnalysis({
      reference_midi: Array<null>(10).fill(null),
      aligned_midi: Array<null>(10).fill(null),
    });

    expect(wordStats(linePractice().words, analysis)[0]).toEqual({
      text: "Hola",
      reference: null,
      voice: null,
      offset: null,
    });
  });
});
