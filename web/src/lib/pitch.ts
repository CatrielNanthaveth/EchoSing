const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/** Fractional MIDI note of a frequency (A4 = 440 Hz = 69). */
export function hzToMidi(hz: number): number {
  return 69 + 12 * Math.log2(hz / 440);
}

/** Nearest note name, e.g. 440 -> "A4"; null when unvoiced. */
export function noteName(hz: number): string | null {
  if (!(hz > 0)) return null;
  const midi = Math.round(hzToMidi(hz));
  return `${NOTE_NAMES[midi % 12] ?? "?"}${Math.floor(midi / 12) - 1}`;
}

/** RMS level as 0-1 on a -60..0 dBFS scale, for meters. */
export function levelFraction(rms: number): number {
  if (!(rms > 0)) return 0;
  const db = 20 * Math.log10(rms);
  return Math.min(1, Math.max(0, (db + 60) / 60));
}
