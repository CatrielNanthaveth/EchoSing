const KEY = "echosing.playerName";
export const DEFAULT_PLAYER_NAME = "Jugador";
/** Same limit as the API. */
export const MAX_PLAYER_NAME = 50;

/** Name used in the last session. */
export function loadPlayerName(): string {
  try {
    return localStorage.getItem(KEY) ?? DEFAULT_PLAYER_NAME;
  } catch {
    return DEFAULT_PLAYER_NAME;
  }
}

/** Clean up a typed name: trimmed, capped, never empty. */
export function normalizePlayerName(name: string): string {
  return name.trim().slice(0, MAX_PLAYER_NAME) || DEFAULT_PLAYER_NAME;
}

export function savePlayerName(name: string): void {
  try {
    localStorage.setItem(KEY, normalizePlayerName(name));
  } catch {
    // Storage blocked: the name is only used for this session.
  }
}
