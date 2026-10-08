/** Delay between asking to play and the first sample, so it starts cleanly. */
const START_LEAD_S = 0.1;

/**
 * Plays a decoded track and tells the song position from the AudioContext
 * clock (sample accurate, unlike `<audio>.currentTime`).
 */
export class Playback {
  readonly #context: BaseAudioContext;
  readonly #buffer: AudioBuffer;
  readonly #destination: AudioNode;
  #source: AudioBufferSourceNode | null = null;
  #startedAt = 0;

  constructor(context: BaseAudioContext, buffer: AudioBuffer, destination?: AudioNode) {
    this.#context = context;
    this.#buffer = buffer;
    this.#destination = destination ?? context.destination;
  }

  get durationMs(): number {
    return this.#buffer.duration * 1000;
  }

  get playing(): boolean {
    return this.#source !== null;
  }

  /** Context time (s) at which song time 0 is played. */
  get startedAt(): number {
    return this.#startedAt;
  }

  /**
   * Play from the beginning.
   *
   * @param onEnded Called when the track finishes on its own (not on stop()).
   */
  start(onEnded?: () => void): void {
    this.stop();
    const source = this.#context.createBufferSource();
    source.buffer = this.#buffer;
    source.connect(this.#destination);
    source.onended = () => {
      if (this.#source !== source) return; // stopped or restarted
      this.#source = null;
      onEnded?.();
    };
    this.#startedAt = this.#context.currentTime + START_LEAD_S;
    source.start(this.#startedAt);
    this.#source = source;
  }

  stop(): void {
    const source = this.#source;
    if (source === null) return;
    this.#source = null;
    source.stop();
    source.disconnect();
  }

  /** Song time (ms) of the audio being scheduled now; 0 before the start. */
  positionMs(): number {
    if (this.#source === null) return 0;
    return Math.max(0, (this.#context.currentTime - this.#startedAt) * 1000);
  }

  /** Song time (ms) at a given context time, e.g. a microphone frame's. */
  songTimeAt(contextTime: number): number {
    return (contextTime - this.#startedAt) * 1000;
  }
}
