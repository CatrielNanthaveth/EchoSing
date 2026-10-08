let shared: AudioContext | null = null;

/**
 * The app's single AudioContext.
 *
 * Playback and the microphone share it so the song position and the
 * timestamps of captured audio come from the same clock. Browsers only let it
 * start after a user gesture: call this from a click handler.
 */
export function getAudioContext(): AudioContext {
  if (shared === null || shared.state === "closed") {
    shared = new AudioContext({ latencyHint: "interactive" });
  }
  return shared;
}

/** Time from scheduling a sample to hearing it, as reported by the browser. */
export function outputLatencyMs(context: BaseAudioContext): number {
  if (!(context instanceof AudioContext)) return 0;
  return ((context.baseLatency || 0) + (context.outputLatency || 0)) * 1000;
}

/** Download and decode an audio file into memory. */
export async function loadTrack(
  context: BaseAudioContext,
  url: string,
  signal?: AbortSignal,
): Promise<AudioBuffer> {
  const response = await fetch(url, { signal: signal ?? null });
  if (!response.ok) {
    throw new Error(`No se pudo descargar la pista (HTTP ${response.status})`);
  }
  return context.decodeAudioData(await response.arrayBuffer());
}
