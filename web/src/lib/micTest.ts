import { SILENCE_RMS, type VoiceFrame } from "../audio/frameAnalyzer";
import { YIN_THRESHOLD } from "../audio/yin";

/** What the microphone test measured while the player sang. */
export interface MicTestStats {
  frames: number;
  /** Frames with a detected pitch. */
  voicedShare: number;
  /** Frames dropped by the silence gate (too quiet). */
  gatedShare: number;
  /** Frames loud enough but not periodic enough for YIN. */
  rejectedShare: number;
  /** Median level of the windows, in dBFS. */
  medianLevelDb: number | null;
  /** Level of the silence gate, in dBFS. */
  gateDb: number;
  /** Median clarity of the voiced frames (1 = perfectly periodic). */
  voicedClarity: number | null;
  /** Median clarity of the rejected frames (how close they came). */
  rejectedClarity: number | null;
  /** Clarity needed to be voiced. */
  clarityThreshold: number;
  /** Median length of the stretches with voice, in ms. */
  medianVoicedRunMs: number | null;
  /** Median detected note (Hz). */
  medianF0: number | null;
  /** Frames with voice without the high-pass filter (null: no diagnostics). */
  rawVoicedShare: number | null;
  /** Median share of the energy below the filter cutoff, non-silent frames. */
  lowFrequencyShare: number | null;
  /** Frames whose unfiltered window has a click-like peak. */
  clickShare: number | null;
}

/** Peak / RMS above this is a click (a sung vowel stays below ~4). */
export const CLICK_CREST = 8;

function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2
    ? (sorted[middle] ?? null)
    : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

function toDb(rms: number): number {
  return 20 * Math.log10(Math.max(rms, 1e-6));
}

function round(value: number | null, digits: number): number | null {
  return value === null ? null : Math.round(value * 10 ** digits) / 10 ** digits;
}

/** Summarize frames recorded while singing continuously. */
export function micTestStats(frames: readonly VoiceFrame[]): MicTestStats {
  const total = Math.max(frames.length, 1);
  const voiced = frames.filter((frame) => frame.f0 > 0);
  const gated = frames.filter((frame) => frame.gated);
  const rejected = frames.filter((frame) => !frame.gated && frame.f0 <= 0);

  const runs: number[] = [];
  let run = 0;
  for (const frame of frames) {
    if (frame.f0 > 0) {
      run++;
    } else if (run > 0) {
      runs.push(run);
      run = 0;
    }
  }
  if (run > 0) runs.push(run);
  const hopMs =
    frames.length > 1
      ? (((frames.at(-1)?.time ?? 0) - (frames[0]?.time ?? 0)) * 1000) /
        (frames.length - 1)
      : 0;

  return {
    frames: frames.length,
    voicedShare: round(voiced.length / total, 3) ?? 0,
    gatedShare: round(gated.length / total, 3) ?? 0,
    rejectedShare: round(rejected.length / total, 3) ?? 0,
    medianLevelDb: round(median(frames.map((frame) => toDb(frame.windowRms))), 1),
    gateDb: Math.round(toDb(SILENCE_RMS) * 10) / 10,
    voicedClarity: round(median(voiced.map((frame) => frame.clarity)), 2),
    rejectedClarity: round(median(rejected.map((frame) => frame.clarity)), 2),
    clarityThreshold: 1 - YIN_THRESHOLD,
    medianVoicedRunMs: round(median(runs.map((length) => length * hopMs)), 0),
    medianF0: round(median(voiced.map((frame) => frame.f0)), 0),
    ...diagnosticStats(frames),
  };
}

function diagnosticStats(
  frames: readonly VoiceFrame[],
): Pick<MicTestStats, "rawVoicedShare" | "lowFrequencyShare" | "clickShare"> {
  const diagnosed = frames.flatMap((frame) =>
    frame.diagnostics === undefined ? [] : [{ frame, d: frame.diagnostics }],
  );
  if (diagnosed.length === 0) {
    return { rawVoicedShare: null, lowFrequencyShare: null, clickShare: null };
  }
  const audible = diagnosed.filter(({ frame }) => !frame.gated);
  return {
    rawVoicedShare: round(
      diagnosed.filter(({ d }) => d.rawF0 > 0).length / diagnosed.length,
      3,
    ),
    lowFrequencyShare: round(median(audible.map(({ d }) => d.lowFrequencyShare)), 2),
    clickShare: round(
      diagnosed.filter(({ d }) => d.crest > CLICK_CREST).length / diagnosed.length,
      3,
    ),
  };
}

/** What the numbers mean for the player. */
export function micTestAdvice(stats: MicTestStats): string[] {
  if (stats.frames === 0) return ["No llegó audio del micrófono."];
  const advice: string[] = [];
  if (stats.voicedShare >= 0.8) {
    advice.push("Tu voz se detecta bien.");
  } else {
    advice.push(
      `Solo se detectó tu voz en el ${String(Math.round(stats.voicedShare * 100))}% del tiempo.`,
    );
  }
  if (stats.gatedShare >= 0.15) {
    advice.push(
      "El micrófono te capta bajo: acercate, subí la ganancia del micrófono en el sistema o cantá más fuerte.",
    );
  }
  if (stats.clickShare !== null && stats.clickShare >= 0.05) {
    advice.push(
      "Hay clics en el audio del micrófono: probá otro puerto USB o desactivá las mejoras de audio de Windows para este micrófono.",
    );
  }
  if (
    stats.rawVoicedShare !== null &&
    stats.voicedShare - stats.rawVoicedShare >= 0.05
  ) {
    advice.push(
      `El filtro de graves recupera el ${String(Math.round((stats.voicedShare - stats.rawVoicedShare) * 100))}% de tu voz (el micrófono capta mucho grave de cerca).`,
    );
  }
  if (stats.rejectedShare >= 0.15) {
    advice.push(
      "Hay volumen pero el sonido no es lo bastante limpio para reconocer la nota (ruido, aire en la voz o eco).",
    );
  }
  return advice;
}
