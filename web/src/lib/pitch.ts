const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/** Fractional MIDI note of a frequency (A4 = 440 Hz = 69). */
export function hzToMidi(hz: number): number {
  return 69 + 12 * Math.log2(hz / 440);
}

/** Name of the nearest note of a MIDI number, e.g. 69.2 -> "A4". */
export function midiNoteName(midi: number): string {
  const nearest = Math.round(midi);
  const pitchClass = ((nearest % 12) + 12) % 12;
  return `${NOTE_NAMES[pitchClass] ?? "?"}${Math.floor(nearest / 12) - 1}`;
}

/** Nearest note name, e.g. 440 -> "A4"; null when unvoiced. */
export function noteName(hz: number): string | null {
  if (!(hz > 0)) return null;
  return midiNoteName(hzToMidi(hz));
}

/** RMS level as 0-1 on a -60..0 dBFS scale, for meters. */
export function levelFraction(rms: number): number {
  if (!(rms > 0)) return 0;
  const db = 20 * Math.log10(rms);
  return Math.min(1, Math.max(0, (db + 60) / 60));
}
