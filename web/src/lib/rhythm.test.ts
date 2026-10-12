import { describe, expect, it } from "vitest";

import { rhythmAnalysis } from "../test/factories";
import { attackRows, rhythmAdvice } from "./rhythm";

describe("rhythmAdvice", () => {
  it("counts attacks on time, misses and extras", () => {
    expect(rhythmAdvice(rhythmAnalysis())).toEqual([
      "Clavaste 2 de 4 golpes a tiempo.",
      "Te faltó 1 golpe.",
      "Sobró 1 golpe que no está en la original.",
    ]);
  });

  it.each([
    [90, "Ibas ~90 ms atrasado."],
    [-60, "Ibas ~60 ms adelantado."],
  ])("explains a median offset of %d ms", (offset, text) => {
    expect(rhythmAdvice(rhythmAnalysis({ timing_offset_ms: offset }))).toContain(text);
  });

  it("uses plurals", () => {
    const advice = rhythmAdvice(rhythmAnalysis({ missed: 3, extra: 2 }));

    expect(advice).toContain("Te faltaron 3 golpes.");
    expect(advice).toContain("Sobraron 2 golpes que no están en la original.");
  });

  it("explains lines without attacks or without the singer", () => {
    expect(
      rhythmAdvice(
        rhythmAnalysis({
          result: {
            scorable: false,
            score: null,
            accuracy: null,
            hit: false,
            voiced_frames: 1,
          },
        }),
      ),
    ).toEqual(["Este verso casi no tiene sílabas marcadas en la original: no puntúa."]);
    expect(rhythmAdvice(rhythmAnalysis({ pairs: [] }))).toEqual([
      "No se detectaron tus golpes en este verso.",
    ]);
  });
});

describe("attackRows", () => {
  it("lists every reference attack with its match", () => {
    expect(attackRows(rhythmAnalysis())).toEqual([
      { index: 0, referenceMs: 0, sungMs: 10, offsetMs: 10 },
      { index: 1, referenceMs: 200, sungMs: 270, offsetMs: 70 },
      { index: 2, referenceMs: 400, sungMs: 380, offsetMs: -20 },
      { index: 3, referenceMs: 600, sungMs: null, offsetMs: null },
    ]);
  });
});
