import { Yin } from "./yin";

/** Name the AudioWorklet processor is registered under. */
export const VOICE_PROCESSOR = "voice-processor";

/** Analysis window in samples (~43 ms at 48 kHz: two periods of 50 Hz). */
export const WINDOW_SIZE = 2048;
/** Samples between frames (~10.7 ms at 48 kHz). */
export const HOP_SIZE = 512;

/** Window RMS below which there is no voice (~-46 dBFS); skips pitch search. */
export const SILENCE_RMS = 0.005;

/** One analysis frame of microphone audio. */
export interface VoiceFrame {
  /** AudioContext time (s) of the center of the analysis window. */
  time: number;
  /** RMS level of the central hop of the window (sharp in time, for onsets). */
  rms: number;
  /** Pitch in Hz, 0 when unvoiced or silent. */
  f0: number;
  /** 0-1 periodicity of the window, also when unvoiced (0 when silent). */
  clarity: number;
  /** RMS level of the whole window (what the silence gate compares). */
  windowRms: number;
  /** Whether the window was below the silence gate (no pitch search). */
  gated: boolean;
}

/**
 * Slices a stream of audio blocks into overlapping windows and emits one
 * frame every `hopSize` samples, timestamped on the AudioContext clock.
 *
 * Runs inside the AudioWorklet; kept free of worklet globals so it can be
 * tested directly.
 */
export class FrameAnalyzer {
  readonly #sampleRate: number;
  readonly #emit: (frame: VoiceFrame) => void;
  readonly #window: Float32Array;
  readonly #hopSize: number;
  readonly #yin: Yin;
  /** Samples received since the last frame. */
  #pending = 0;
  /** Valid samples in the window (it starts empty). */
  #filled = 0;

  constructor(
    sampleRate: number,
    emit: (frame: VoiceFrame) => void,
    windowSize = WINDOW_SIZE,
    hopSize = HOP_SIZE,
  ) {
    this.#sampleRate = sampleRate;
    this.#emit = emit;
    this.#window = new Float32Array(windowSize);
    this.#hopSize = hopSize;
    this.#yin = new Yin(sampleRate, windowSize);
  }

  /**
   * Add a block of samples.
   *
   * @param block Mono samples.
   * @param firstFrame AudioContext sample index of `block[0]`.
   */
  push(block: Float32Array, firstFrame: number): void {
    const size = this.#window.length;
    let offset = 0;
    while (offset < block.length) {
      const take = Math.min(this.#hopSize - this.#pending, block.length - offset);
      // Shift the window left and append the new samples at the end.
      this.#window.copyWithin(0, take);
      this.#window.set(block.subarray(offset, offset + take), size - take);
      offset += take;
      this.#pending += take;
      this.#filled = Math.min(size, this.#filled + take);
      if (this.#pending === this.#hopSize) {
        this.#pending = 0;
        if (this.#filled === size) this.#analyze(firstFrame + offset);
      }
    }
  }

  /** Analyze the window that ends just before sample `endFrame`. */
  #analyze(endFrame: number): void {
    const size = this.#window.length;
    const centerFrame = endFrame - size / 2;
    const hopStart = (size - this.#hopSize) / 2;
    let energy = 0;
    let hopEnergy = 0;
    for (let i = 0; i < size; i++) {
      const sample = this.#window[i] ?? 0;
      energy += sample * sample;
      if (i >= hopStart && i < hopStart + this.#hopSize) hopEnergy += sample * sample;
    }
    const windowRms = Math.sqrt(energy / size);
    const gated = windowRms < SILENCE_RMS;
    const pitch = gated ? { f0: 0, clarity: 0 } : this.#yin.estimate(this.#window);
    this.#emit({
      time: centerFrame / this.#sampleRate,
      rms: Math.sqrt(hopEnergy / this.#hopSize),
      f0: pitch.f0,
      clarity: pitch.clarity,
      windowRms,
      gated,
    });
  }
}
