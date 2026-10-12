import type { components } from "../api/schema";

export type RhythmAnalysis = components["schemas"]["RhythmAnalysis"];

/** Below this median offset (ms) the singer is "on time". */
const ON_TIME_MS = 40;

/** Short, concrete feedback for a rapped line. */
export function rhythmAdvice(analysis: RhythmAnalysis): string[] {
  if (!analysis.result.scorable) {
    return ["Este verso casi no tiene sílabas marcadas en la original: no puntúa."];
  }
  const total = analysis.reference_onsets_ms.length;
  const onTime = analysis.pairs.filter(
    (pair) => Math.abs(pair.offset_ms) <= ON_TIME_MS,
  ).length;
  if (analysis.pairs.length === 0)
    return ["No se detectaron tus golpes en este verso."];

  const advice = [`Clavaste ${String(onTime)} de ${String(total)} golpes a tiempo.`];
  const offset = analysis.timing_offset_ms;
  if (offset !== null && Math.abs(offset) >= ON_TIME_MS / 2) {
    advice.push(
      `Ibas ~${String(Math.round(Math.abs(offset)))} ms ${offset > 0 ? "atrasado" : "adelantado"}.`,
    );
  }
  if (analysis.missed > 0) {
    advice.push(
      `Te ${analysis.missed === 1 ? "faltó 1 golpe" : `faltaron ${String(analysis.missed)} golpes`}.`,
    );
  }
  if (analysis.extra === 1) {
    advice.push("Sobró 1 golpe que no está en la original.");
  } else if (analysis.extra > 1) {
    advice.push(
      `Sobraron ${String(analysis.extra)} golpes que no están en la original.`,
    );
  }
  return advice;
}

/** How each reference attack went: matched (with offset) or missed. */
export interface AttackRow {
  index: number;
  referenceMs: number;
  sungMs: number | null;
  offsetMs: number | null;
}

export function attackRows(analysis: RhythmAnalysis): AttackRow[] {
  const byReference = new Map(analysis.pairs.map((pair) => [pair.reference, pair]));
  return analysis.reference_onsets_ms.map((referenceMs, index) => {
    const pair = byReference.get(index);
    return {
      index,
      referenceMs,
      sungMs: pair === undefined ? null : (analysis.sung_onsets_ms[pair.sung] ?? null),
      offsetMs: pair === undefined ? null : pair.offset_ms,
    };
  });
}
