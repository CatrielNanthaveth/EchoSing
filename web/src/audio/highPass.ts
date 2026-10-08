/** Cutoff below any sung fundamental (YIN searches from 70 Hz). */
export const HIGH_PASS_HZ = 60;

/**
 * Second-order Butterworth high-pass (RBJ biquad), sample by sample.
 *
 * Removes DC, rumble and the bass boost of a close cardioid microphone
 * (proximity effect, breath pops), which can dominate the window and hide
 * the voice's periodicity from YIN. State persists across blocks.
 */
export class HighPass {
  readonly #b0: number;
  readonly #b1: number;
  readonly #b2: number;
  readonly #a1: number;
  readonly #a2: number;
  #x1 = 0;
  #x2 = 0;
  #y1 = 0;
  #y2 = 0;

  constructor(sampleRate: number, cutoffHz = HIGH_PASS_HZ) {
    const w0 = (2 * Math.PI * cutoffHz) / sampleRate;
    const cos = Math.cos(w0);
    const alpha = Math.sin(w0) / Math.SQRT2; // Q = 1/sqrt(2)
    const a0 = 1 + alpha;
    this.#b0 = (1 + cos) / 2 / a0;
    this.#b1 = -(1 + cos) / a0;
    this.#b2 = (1 + cos) / 2 / a0;
    this.#a1 = (-2 * cos) / a0;
    this.#a2 = (1 - alpha) / a0;
  }

  /** Filter one sample. */
  next(x: number): number {
    const y =
      this.#b0 * x +
      this.#b1 * this.#x1 +
      this.#b2 * this.#x2 -
      this.#a1 * this.#y1 -
      this.#a2 * this.#y2;
    this.#x2 = this.#x1;
    this.#x1 = x;
    this.#y2 = this.#y1;
    this.#y1 = y;
    return y;
  }
}
