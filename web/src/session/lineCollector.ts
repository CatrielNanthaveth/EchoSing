import type { LyricLine } from "../api/types";

/** Frames kept after a line ends: the server shifts the curve by the latency. */
export const LINE_TAIL_MS = 300;
/** Maximum frames per message accepted by the server. */
const MAX_FRAMES = 6000;
/** Level of silence and of missing frames (dBFS); the server accepts >= -120. */
export const SILENT_DB = -90;

/** Microphone level of an RMS value in dBFS, floored and rounded to 0.1 dB. */
export function levelDb(rms: number): number {
  if (!(rms > 0)) return SILENT_DB;
  return Math.max(SILENT_DB, Math.round(200 * Math.log10(rms)) / 10);
}

/** The pitch sung over one line, ready to send as `line_pitch`. */
export interface SungLine {
  lineIndex: number;
  hopMs: number;
  /** Pitch per frame from the line start, 0 where unvoiced. */
  f0Hz: number[];
  /** Microphone level per frame (dBFS), same frames as `f0Hz`. */
  levelDb: number[];
}

interface Frame {
  songMs: number;
  f0: number;
  db: number;
}

/**
 * Groups microphone frames by lyric line, in song time.
 *
 * Frames arrive every `hopMs` with an arbitrary phase; each line is resampled
 * to frames exactly at `start_ms + k * hopMs`, as the protocol expects. A line
 * is emitted once frames reach `end_ms + LINE_TAIL_MS`.
 */
export class LineCollector {
  readonly #lines: readonly LyricLine[];
  readonly #hopMs: number;
  readonly #onLine: (line: SungLine) => void;
  readonly #frames: Frame[] = [];
  /** Index of the next line to emit. */
  #next = 0;

  constructor(
    lines: readonly LyricLine[],
    hopMs: number,
    onLine: (line: SungLine) => void,
  ) {
    this.#lines = [...lines].sort((a, b) => a.start_ms - b.start_ms);
    this.#hopMs = hopMs;
    this.#onLine = onLine;
  }

  /**
   * Add a frame; frames must arrive in time order.
   *
   * @param db Microphone level (dBFS), see `levelDb`.
   */
  add(songMs: number, f0: number, db = SILENT_DB): void {
    this.#frames.push({ songMs, f0: f0 > 0 ? f0 : 0, db });
    let line = this.#lines[this.#next];
    while (line !== undefined && songMs >= line.end_ms + LINE_TAIL_MS) {
      this.#emit(line);
      this.#next++;
      line = this.#lines[this.#next];
    }
    this.#prune();
  }

  /**
   * Emit the lines that started but did not reach their tail (e.g. the song
   * ended right after the last line). Lines never reached are not emitted.
   */
  flush(): void {
    const lastMs = this.#frames.at(-1)?.songMs ?? -Infinity;
    let line = this.#lines[this.#next];
    while (line !== undefined && lastMs >= line.start_ms) {
      this.#emit(line);
      this.#next++;
      line = this.#lines[this.#next];
    }
    this.#frames.length = 0;
  }

  #emit(line: LyricLine): void {
    const hop = this.#hopMs;
    const count = Math.min(
      MAX_FRAMES,
      Math.ceil((line.end_ms + LINE_TAIL_MS - line.start_ms) / hop),
    );
    const f0Hz = new Array<number>(count).fill(0);
    const levels = new Array<number>(count).fill(SILENT_DB);
    let cursor = 0;
    for (let k = 0; k < count; k++) {
      const target = line.start_ms + k * hop;
      // Advance to the frame nearest to the target (frames are sorted).
      while (
        cursor + 1 < this.#frames.length &&
        Math.abs((this.#frames[cursor + 1]?.songMs ?? Infinity) - target) <=
          Math.abs((this.#frames[cursor]?.songMs ?? Infinity) - target)
      ) {
        cursor++;
      }
      const frame = this.#frames[cursor];
      // A gap (e.g. a dropped audio block) counts as unvoiced.
      if (frame !== undefined && Math.abs(frame.songMs - target) <= hop / 2 + 0.01) {
        f0Hz[k] = Math.round(frame.f0 * 10) / 10;
        levels[k] = frame.db;
      }
    }
    this.#onLine({
      lineIndex: line.index,
      hopMs: Math.round(hop * 1000) / 1000,
      f0Hz,
      levelDb: levels,
    });
  }

  /** Drop frames before the next line: they will never be used again. */
  #prune(): void {
    const keepFrom = (this.#lines[this.#next]?.start_ms ?? Infinity) - this.#hopMs;
    let drop = 0;
    while (drop < this.#frames.length && (this.#frames[drop]?.songMs ?? 0) < keepFrom) {
      drop++;
    }
    if (drop > 0) this.#frames.splice(0, drop);
  }
}
