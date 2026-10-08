import type { components } from "../api/schema";

export type Difficulty = components["schemas"]["Difficulty"];

const KEY = "echosing.difficulty";
export const DEFAULT_DIFFICULTY: Difficulty = "normal";

/** Levels in display order, with their labels and what they forgive. */
export const DIFFICULTIES: readonly {
  value: Difficulty;
  label: string;
  hint: string;
}[] = [
  { value: "easy", label: "Fácil", hint: "perdona hasta 1 semitono" },
  { value: "normal", label: "Normal", hint: "perdona hasta ¾ de semitono" },
  { value: "hard", label: "Difícil", hint: "perdona hasta ½ semitono" },
];

export function difficultyLabel(difficulty: Difficulty): string {
  return DIFFICULTIES.find((level) => level.value === difficulty)?.label ?? difficulty;
}

function isDifficulty(value: string | null): value is Difficulty {
  return DIFFICULTIES.some((level) => level.value === value);
}

/** Level chosen last time, or the default. */
export function loadDifficulty(): Difficulty {
  try {
    const stored = localStorage.getItem(KEY);
    return isDifficulty(stored) ? stored : DEFAULT_DIFFICULTY;
  } catch {
    return DEFAULT_DIFFICULTY;
  }
}

export function saveDifficulty(difficulty: Difficulty): void {
  try {
    localStorage.setItem(KEY, difficulty);
  } catch {
    // Storage blocked: the level only applies to this visit.
  }
}
