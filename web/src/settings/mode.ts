import type { components } from "../api/schema";

export type ScoringMode = components["schemas"]["ScoringMode"];

export const DEFAULT_MODE: ScoringMode = "melody";

/** Modes in display order, with their labels and what they score. */
export const MODES: readonly { value: ScoringMode; label: string; hint: string }[] = [
  { value: "melody", label: "Melodía", hint: "puntúa la afinación" },
  {
    value: "rhythm",
    label: "Rap",
    hint: "puntúa el tiempo de cada sílaba, no el tono",
  },
];

export function modeLabel(mode: ScoringMode): string {
  return MODES.find((item) => item.value === mode)?.label ?? mode;
}

function key(songId: string): string {
  return `echosing.mode.${songId}`;
}

function isMode(value: string | null): value is ScoringMode {
  return MODES.some((item) => item.value === value);
}

/** Mode chosen last time for a song (each song remembers its own). */
export function loadMode(songId: string): ScoringMode {
  try {
    const stored = localStorage.getItem(key(songId));
    return isMode(stored) ? stored : DEFAULT_MODE;
  } catch {
    return DEFAULT_MODE;
  }
}

export function saveMode(songId: string, mode: ScoringMode): void {
  try {
    localStorage.setItem(key(songId), mode);
  } catch {
    // Storage blocked: the mode only applies to this visit.
  }
}
