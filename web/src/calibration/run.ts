import type { VoiceFrame } from "../audio/frameAnalyzer";
import type { Microphone } from "../audio/microphone";
import { measureLatency, type CalibrationResult } from "./detect";

export const BEEP_COUNT = 8;
/** 100 BPM: easy to clap along to. */
export const BEEP_INTERVAL_S = 0.6;
/** Silence before the first beep, to hear the background level. */
const LEAD_IN_S = 1.2;
/** Recording kept after the last beep, for late reactions. */
const TAIL_S = 0.8;
const BEEP_HZ = 1000;
const BEEP_S = 0.05;

/** Schedule short beeps with sharp attacks; returns their context times (s). */
export function scheduleBeeps(context: BaseAudioContext, firstAt: number): number[] {
  const times = Array.from(
    { length: BEEP_COUNT },
    (_, i) => firstAt + i * BEEP_INTERVAL_S,
  );
  for (const time of times) {
    const oscillator = context.createOscillator();
    const envelope = context.createGain();
    oscillator.frequency.value = BEEP_HZ;
    envelope.gain.setValueAtTime(0, time);
    envelope.gain.linearRampToValueAtTime(0.5, time + 0.002);
    envelope.gain.exponentialRampToValueAtTime(0.001, time + BEEP_S);
    oscillator.connect(envelope).connect(context.destination);
    oscillator.start(time);
    oscillator.stop(time + BEEP_S + 0.01);
  }
  return times;
}

/**
 * Play the beeps, record the microphone and measure the latency.
 *
 * @param onScheduled Receives the beep times, e.g. to animate the beat.
 */
export async function calibrate(
  context: AudioContext,
  microphone: Microphone,
  onScheduled?: (beepTimes: readonly number[]) => void,
): Promise<CalibrationResult> {
  const frames: VoiceFrame[] = [];
  const unsubscribe = microphone.subscribe((frame) => frames.push(frame));
  try {
    const beeps = scheduleBeeps(context, context.currentTime + LEAD_IN_S);
    onScheduled?.(beeps);
    const endsAt = (beeps.at(-1) ?? context.currentTime) + TAIL_S;
    await new Promise((resolve) =>
      setTimeout(resolve, (endsAt - context.currentTime) * 1000),
    );
    return measureLatency(frames, beeps);
  } finally {
    unsubscribe();
  }
}
