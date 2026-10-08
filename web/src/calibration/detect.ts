import type { VoiceFrame } from "../audio/frameAnalyzer";

/** An onset must rise this many times above the background level. */
const ONSET_RATIO = 4;
/** Absolute minimum onset level (RMS), for very quiet backgrounds. */
const MIN_ONSET_RMS = 0.01;
/** Ignore new onsets this long after one (a clap's ringing, a beep's tail). */
const REFRACTORY_S = 0.15;
/** Where to look for the reaction to a beep, relative to it. */
const SEARCH_FROM_S = -0.15;
const SEARCH_TO_S = 0.6;
/** Offsets farther than this from the median are outliers (s). */
const OUTLIER_S = 0.06;
/** Minimum beeps matched for a reliable result. */
export const MIN_MATCHED = 5;
/** The API accepts latencies in this range (ms). */
const LATENCY_RANGE_MS = [-500, 1000] as const;

export type CalibrationResult =
  | {
      ok: true;
      /** Total audio latency (output + input) in ms. */
      latencyMs: number;
      /** Beeps with a matching onset. */
      matched: number;
      /** Median absolute deviation of the offsets, in ms. */
      spreadMs: number;
    }
  | { ok: false; reason: "no_signal" | "inconsistent"; matched: number };

function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2
    ? (sorted[middle] ?? NaN)
    : ((sorted[middle - 1] ?? NaN) + (sorted[middle] ?? NaN)) / 2;
}

/**
 * Times where the level jumps above the background: rising edges over a
 * threshold relative to the median level (the background, as sounds are
 * short), with a refractory period.
 */
export function detectOnsets(frames: readonly VoiceFrame[]): number[] {
  if (frames.length === 0) return [];
  const background = median(frames.map((frame) => frame.rms));
  const threshold = Math.max(background * ONSET_RATIO, MIN_ONSET_RMS);
  const onsets: number[] = [];
  let previous = Infinity;
  for (const frame of frames) {
    const rising = frame.rms >= threshold && previous < threshold;
    const last = onsets.at(-1);
    if (rising && (last === undefined || frame.time - last >= REFRACTORY_S)) {
      onsets.push(frame.time);
    }
    previous = frame.rms;
  }
  return onsets;
}

/**
 * Measure the audio latency from beeps and the sounds recorded around them.
 *
 * The player claps (or says "ta") with each beep. A clap heard `out` ms late
 * and recorded `in` ms late shows up `out + in` after the beep was scheduled:
 * exactly the delay of sung frames. With speakers the beep itself is recorded
 * with the same delay, so both ways agree.
 *
 * @param frames Microphone frames covering the beeps.
 * @param beepTimes AudioContext times (s) the beeps were scheduled at.
 */
export function measureLatency(
  frames: readonly VoiceFrame[],
  beepTimes: readonly number[],
): CalibrationResult {
  const onsets = detectOnsets(frames);
  const offsets: number[] = [];
  for (const beep of beepTimes) {
    const onset = onsets.find(
      (time) => time >= beep + SEARCH_FROM_S && time <= beep + SEARCH_TO_S,
    );
    if (onset !== undefined) offsets.push(onset - beep);
  }
  if (offsets.length < MIN_MATCHED) {
    return { ok: false, reason: "no_signal", matched: offsets.length };
  }

  const center = median(offsets);
  const inliers = offsets.filter((offset) => Math.abs(offset - center) <= OUTLIER_S);
  if (inliers.length < MIN_MATCHED) {
    return { ok: false, reason: "inconsistent", matched: inliers.length };
  }
  const latency = median(inliers);
  const spread = median(inliers.map((offset) => Math.abs(offset - latency)));
  const [min, max] = LATENCY_RANGE_MS;
  return {
    ok: true,
    latencyMs: Math.min(max, Math.max(min, Math.round(latency * 1000))),
    matched: inliers.length,
    spreadMs: Math.round(spread * 1000),
  };
}
