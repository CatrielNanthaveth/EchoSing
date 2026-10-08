/** Pitch of one window: `f0` is 0 when no clear pitch is found. */
export interface PitchEstimate {
  /** Fundamental frequency in Hz, 0 if unvoiced. */
  f0: number;
  /**
   * 0-1: how periodic the window is (1 - YIN aperiodicity); also reported
   * when unvoiced (how close it came to the threshold).
   */
  clarity: number;
}

export interface YinOptions {
  /** Lowest pitch searched (Hz); bounds the longest period. */
  minHz?: number;
  /** Highest pitch searched (Hz). */
  maxHz?: number;
  /** Aperiodicity below which a period is accepted (YIN paper: 0.10-0.15). */
  threshold?: number;
}

/** Default aperiodicity threshold (clarity above 1 - this is voiced). */
export const YIN_THRESHOLD = 0.15;

/**
 * YIN pitch detector (de Cheveigné & Kawahara, 2002).
 *
 * Buffers are allocated once: `estimate` runs ~90 times per second inside the
 * AudioWorklet and must not create garbage.
 */
export class Yin {
  readonly #sampleRate: number;
  readonly #integration: number;
  readonly #minPeriod: number;
  readonly #maxPeriod: number;
  readonly #threshold: number;
  /** Cumulative mean normalized difference, indexed by period. */
  readonly #cmnd: Float32Array;

  constructor(sampleRate: number, windowSize: number, options: YinOptions = {}) {
    const { minHz = 70, maxHz = 1000, threshold = YIN_THRESHOLD } = options;
    this.#sampleRate = sampleRate;
    this.#integration = windowSize >> 1;
    this.#minPeriod = Math.max(2, Math.floor(sampleRate / maxHz));
    this.#maxPeriod = Math.min(this.#integration, Math.ceil(sampleRate / minHz));
    this.#threshold = threshold;
    this.#cmnd = new Float32Array(this.#maxPeriod + 2);
  }

  estimate(window: Float32Array): PitchEstimate {
    const cmnd = this.#cmnd;
    const size = this.#integration;
    const last = this.#maxPeriod + 1;

    // Steps 2-3: difference function, normalized by its running mean.
    cmnd[0] = 1;
    let runningSum = 0;
    for (let tau = 1; tau <= last; tau++) {
      let difference = 0;
      for (let j = 0; j < size; j++) {
        const delta = (window[j] ?? 0) - (window[j + tau] ?? 0);
        difference += delta * delta;
      }
      runningSum += difference;
      cmnd[tau] = runningSum > 0 ? (difference * tau) / runningSum : 1;
    }

    // Step 4: first dip under the threshold, followed to its local minimum.
    let period = -1;
    let lowest = 1;
    for (let tau = this.#minPeriod; tau < last; tau++) {
      const value = cmnd[tau] ?? 1;
      if (value < lowest) lowest = value;
      if (value < this.#threshold) {
        while (tau + 1 < last && (cmnd[tau + 1] ?? 1) < (cmnd[tau] ?? 1)) tau++;
        period = tau;
        break;
      }
    }
    // Unvoiced: still report how periodic it was (diagnostics, tuning).
    if (period < 0) return { f0: 0, clarity: Math.max(0, 1 - lowest) };

    // Step 5: parabolic interpolation for a sub-sample period.
    const before = cmnd[period - 1] ?? 1;
    const at = cmnd[period] ?? 1;
    const after = cmnd[period + 1] ?? 1;
    const curvature = before - 2 * at + after;
    const shift = curvature > 0 ? (before - after) / (2 * curvature) : 0;
    return {
      f0: this.#sampleRate / (period + shift),
      clarity: Math.max(0, Math.min(1, 1 - at)),
    };
  }
}
