import type { PitchResponse } from "../api/types";

/** Guide volume: audible over the track without covering the singer. */
export const GUIDE_GAIN = 0.12;
/** Reference frames below this confidence are silent (as in scoring). */
const MIN_CONFIDENCE = 50;
/** Smoothing of pitch and volume changes (s): avoids clicks and zipper noise. */
const GLIDE_S = 0.015;
/** Pitch changes smaller than this (semitones) are not scheduled. */
const PITCH_STEP = 0.05;

function midiToHz(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

/**
 * Play the reference melody of a line as a soft tone, in sync with the track.
 *
 * @param startAt AudioContext time at which the reference's first frame plays.
 * @returns A function that stops the guide.
 */
export function playGuide(
  context: BaseAudioContext,
  reference: PitchResponse,
  startAt: number,
  destination: AudioNode = context.destination,
): () => void {
  const oscillator = context.createOscillator();
  const volume = context.createGain();
  oscillator.type = "triangle";
  volume.gain.value = 0;
  oscillator.connect(volume).connect(destination);

  const hop = reference.hop_ms / 1000;
  let voiced = false;
  let lastMidi = Number.NaN;
  reference.midi.forEach((midi, frame) => {
    const time = startAt + frame * hop;
    const sung = midi !== null && (reference.confidence[frame] ?? 0) >= MIN_CONFIDENCE;
    const changed =
      Number.isNaN(lastMidi) || Math.abs((midi ?? 0) - lastMidi) >= PITCH_STEP;
    if (sung && changed) {
      // Jump when the note starts after a silence, glide while it is sung.
      if (voiced) oscillator.frequency.setTargetAtTime(midiToHz(midi), time, GLIDE_S);
      else oscillator.frequency.setValueAtTime(midiToHz(midi), time);
      lastMidi = midi;
    }
    if (sung !== voiced) {
      volume.gain.setTargetAtTime(sung ? GUIDE_GAIN : 0, time, GLIDE_S);
      voiced = sung;
    }
  });
  const end = startAt + reference.midi.length * hop;
  volume.gain.setTargetAtTime(0, end, GLIDE_S);
  oscillator.start(startAt);
  oscillator.stop(end + 0.2);

  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    try {
      oscillator.stop();
    } catch {
      // Already stopped on schedule.
    }
    oscillator.disconnect();
    volume.disconnect();
  };
}
