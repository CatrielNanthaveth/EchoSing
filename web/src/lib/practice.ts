import type { LineAnalysis, PracticeWord } from "../api/types";

/** One point of the practice chart. */
export interface ChartRow {
  /** Seconds from the line start. */
  timeS: number;
  /** Reference pitch (MIDI), null where the original has no voice. */
  reference: number | null;
  /** Player's pitch (MIDI), null where there was no voice. */
  voice: number | null;
}

/**
 * Chart points of a line.
 *
 * @param aligned Use the pitch matched to each reference frame (the rhythm
 *   is corrected: only intonation shows) instead of what was sung when.
 */
export function chartRows(analysis: LineAnalysis, aligned: boolean): ChartRow[] {
  const voice = aligned ? analysis.aligned_midi : analysis.sung_midi;
  return analysis.reference_midi.map((reference, frame) => ({
    timeS: Math.round(frame * analysis.hop_ms) / 1000,
    reference,
    voice: voice[frame] ?? null,
  }));
}

/** Y range covering both curves with a semitone of margin. */
export function pitchDomain(rows: readonly ChartRow[]): [number, number] {
  const values = rows.flatMap((row) =>
    [row.reference, row.voice].filter((value): value is number => value !== null),
  );
  if (values.length === 0) return [55, 70];
  return [Math.floor(Math.min(...values)) - 1, Math.ceil(Math.max(...values)) + 1];
}

/** Whole-semitone ticks, at most ~8 of them. */
export function pitchTicks([min, max]: [number, number]): number[] {
  const step = Math.max(1, Math.ceil((max - min) / 8));
  const ticks: number[] = [];
  for (let midi = Math.ceil(min); midi <= max; midi += step) ticks.push(midi);
  return ticks;
}

/** Below these the line is "on pitch" / "on time". */
const PITCH_OK_SEMITONES = 0.3;
const TIMING_OK_MS = 60;

function semitones(value: number): string {
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  return `${String(rounded).replace(".", ",")} semitono${rounded === 1 ? "" : "s"}`;
}

/** Short, concrete feedback for a sung line. */
export function practiceAdvice(analysis: LineAnalysis): string[] {
  if (!analysis.result.scorable) {
    return ["Este verso casi no tiene melodía en la original: no puntúa."];
  }
  const advice: string[] = [];
  const pitch = analysis.pitch_offset_semitones;
  const timing = analysis.timing_offset_ms;
  if (pitch === null || timing === null) {
    return ["No se detectó tu voz en este verso."];
  }
  advice.push(
    Math.abs(pitch) < PITCH_OK_SEMITONES
      ? "Afinación centrada en la melodía."
      : `Cantaste ~${semitones(pitch)} más ${pitch < 0 ? "grave" : "agudo"}.`,
  );
  advice.push(
    Math.abs(timing) < TIMING_OK_MS
      ? "Entraste a tiempo."
      : `Ibas ~${String(Math.round(Math.abs(timing)))} ms ${timing > 0 ? "atrasado" : "adelantado"}.`,
  );
  if (analysis.octave_shift !== 0) {
    const octaves = Math.abs(analysis.octave_shift) / 12;
    advice.push(
      `Cantaste ${octaves === 1 ? "una octava" : `${String(octaves)} octavas`} más ${
        analysis.octave_shift < 0 ? "grave" : "aguda"
      } (no resta puntos; el gráfico la acerca a la melodía).`,
    );
  }
  return advice;
}

/** How one word was sung, averaged over its frames. */
export interface WordStat {
  text: string;
  /** Mean reference pitch (MIDI), null if the original has no voice there. */
  reference: number | null;
  /** Mean pitch matched to it (MIDI), null if nothing was matched. */
  voice: number | null;
  /** Mean signed difference (semitones), null without both. */
  offset: number | null;
}

function mean(values: readonly number[]): number | null {
  return values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length;
}

/** Per-word averages of the aligned curves (the table view of the chart). */
export function wordStats(
  words: readonly PracticeWord[],
  analysis: LineAnalysis,
): WordStat[] {
  const hop = analysis.hop_ms;
  return words.map((word) => {
    const first = Math.max(0, Math.floor(word.start_ms / hop));
    const last = Math.min(analysis.reference_midi.length, Math.ceil(word.end_ms / hop));
    const references: number[] = [];
    const voices: number[] = [];
    const offsets: number[] = [];
    for (let frame = first; frame < last; frame++) {
      const reference = analysis.reference_midi[frame] ?? null;
      const voice = analysis.aligned_midi[frame] ?? null;
      if (reference !== null) references.push(reference);
      if (voice !== null) voices.push(voice);
      if (reference !== null && voice !== null) offsets.push(voice - reference);
    }
    return {
      text: word.text,
      reference: mean(references),
      voice: mean(voices),
      offset: mean(offsets),
    };
  });
}
