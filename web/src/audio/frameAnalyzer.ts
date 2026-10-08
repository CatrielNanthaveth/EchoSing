import { HIGH_PASS_HZ, HighPass } from "./highPass";
import { Yin } from "./yin";

/** Name the AudioWorklet processor is registered under. */
export const VOICE_PROCESSOR = "voice-processor";

/** Analysis window in samples (~43 ms at 48 kHz: two periods of 50 Hz). */
export const WINDOW_SIZE = 2048;
/** Samples between frames (~10.7 ms at 48 kHz). */
export const HOP_SIZE = 512;

/** Window RMS below which there is no voice (~-46 dBFS); skips pitch search. */
export const SILENCE_RMS = 0.005;

/** Measurements to find out why a voice is not detected (microphone test). */
export interface FrameDiagnostics {
  /** Pitch YIN finds without the high-pass filter, 0 if unvoiced. */
  rawF0: number;
  /** Clarity without the high-pass filter. */
  rawClarity: number;
  /** Share (0-1) of the window's energy removed by the high-pass filter. */
  lowFrequencyShare: number;
  /** Peak / RMS of the unfiltered window: high values reveal clicks. */
  crest: number;
}

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
  /** Only while diagnostics are enabled. */
  diagnostics?: FrameDiagnostics;
}

export interface FrameAnalyzerOptions {
  windowSize?: number;
  hopSize?: number;
  /** High-pass cutoff before analysis; null disables the filter. */
  highPassHz?: number | null;
}

/**
 * Slices a stream of audio blocks into overlapping windows and emits one
 * frame every `hopSize` samples, timestamped on the AudioContext clock.
 *
 * Samples are high-passed before analysis (see `HighPass`). Runs inside the
 * AudioWorklet; kept free of worklet globals so it can be tested directly.
 */
export class FrameAnalyzer {
  readonly #sampleRate: number;
  readonly #emit: (frame: VoiceFrame) => void;
  readonly #window: Float32Array;
  /** Unfiltered copy of the window, kept for diagnostics. */
  readonly #rawWindow: Float32Array;
  readonly #filtered: Float32Array;
  readonly #hopSize: number;
  readonly #yin: Yin;
  readonly #highPass: HighPass | null;
  #diagnostics = false;
  /** Samples received since the last frame. */
  #pending = 0;
  /** Valid samples in the window (it starts empty). */
  #filled = 0;

  constructor(
    sampleRate: number,
    emit: (frame: VoiceFrame) => void,
    options: FrameAnalyzerOptions = {},
  ) {
    const {
      windowSize = WINDOW_SIZE,
      hopSize = HOP_SIZE,
      highPassHz = HIGH_PASS_HZ,
    } = options;
    this.#sampleRate = sampleRate;
    this.#emit = emit;
    this.#window = new Float32Array(windowSize);
    this.#rawWindow = new Float32Array(windowSize);
    this.#filtered = new Float32Array(hopSize);
    this.#hopSize = hopSize;
    this.#yin = new Yin(sampleRate, windowSize);
    this.#highPass = highPassHz === null ? null : new HighPass(sampleRate, highPassHz);
  }

  /** Also measure the unfiltered signal in every frame (costs a second YIN). */
  setDiagnostics(enabled: boolean): void {
    this.#diagnostics = enabled;
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
      const raw = block.subarray(offset, offset + take);
      const filtered = this.#filtered.subarray(0, take);
      for (let i = 0; i < take; i++) {
        const sample = raw[i] ?? 0;
        filtered[i] = this.#highPass === null ? sample : this.#highPass.next(sample);
      }
      // Shift the windows left and append the new samples at the end.
      this.#window.copyWithin(0, take);
      this.#window.set(filtered, size - take);
      this.#rawWindow.copyWithin(0, take);
      this.#rawWindow.set(raw, size - take);
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
    const frame: VoiceFrame = {
      time: centerFrame / this.#sampleRate,
      rms: Math.sqrt(hopEnergy / this.#hopSize),
      f0: pitch.f0,
      clarity: pitch.clarity,
      windowRms,
      gated,
    };
    if (this.#diagnostics) frame.diagnostics = this.#diagnose(energy);
    this.#emit(frame);
  }

  #diagnose(filteredEnergy: number): FrameDiagnostics {
    const size = this.#rawWindow.length;
    let rawEnergy = 0;
    let peak = 0;
    for (let i = 0; i < size; i++) {
      const sample = this.#rawWindow[i] ?? 0;
      rawEnergy += sample * sample;
      peak = Math.max(peak, Math.abs(sample));
    }
    const rawRms = Math.sqrt(rawEnergy / size);
    const raw =
      rawRms < SILENCE_RMS
        ? { f0: 0, clarity: 0 }
        : this.#yin.estimate(this.#rawWindow);
    return {
      rawF0: raw.f0,
      rawClarity: raw.clarity,
      lowFrequencyShare:
        rawEnergy > 0 ? Math.min(1, Math.max(0, 1 - filteredEnergy / rawEnergy)) : 0,
      crest: rawRms > 0 ? peak / rawRms : 0,
    };
  }
}
