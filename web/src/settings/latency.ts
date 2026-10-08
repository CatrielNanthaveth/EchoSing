const KEY = "echosing.latencyMs";

/** Latency measured by the last calibration, or null if never calibrated. */
export function loadLatency(): number | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null; // storage blocked (private mode, site settings)
  }
}

/** Remember the latency for the next sessions; false if storage is blocked. */
export function saveLatency(latencyMs: number): boolean {
  try {
    localStorage.setItem(KEY, String(Math.round(latencyMs)));
    return true;
  } catch {
    return false;
  }
}
