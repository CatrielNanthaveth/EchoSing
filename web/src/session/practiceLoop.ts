import type { LineAnalysis, LyricLine } from "../api/types";
import type { Microphone } from "../audio/microphone";
import type { Playback } from "../audio/playback";
import { LINE_TAIL_MS, LineCollector, type SungLine } from "./lineCollector";

/** Music played before the line, so the singer can come in on time. */
export const COUNT_IN_MS = 2000;
/** Pause between attempts, to read the result. */
export const PAUSE_MS = 2500;
/** Playback after the capture tail, so the music does not cut abruptly. */
const OUTRO_MS = 200;

export type LoopPhase =
  | { name: "idle" }
  | { name: "playing"; attempt: number }
  | { name: "scoring"; attempt: number }
  | { name: "result"; attempt: number; analysis: LineAnalysis }
  | { name: "error"; message: string };

export interface PracticeLoopDeps {
  playback: Playback;
  microphone: Microphone;
  /** Time between microphone frames (ms). */
  hopMs: number;
  /** Score one attempt (the server analyzes it). */
  score: (sung: SungLine) => Promise<LineAnalysis>;
  onPhase: (phase: LoopPhase) => void;
  /** Every microphone frame while singing, on the song timeline (live chart). */
  onVoice?: (songMs: number, f0: number) => void;
}

/**
 * Plays one line over and over: count-in, the line while capturing the voice,
 * the score of the attempt, a pause, and again, until stopped.
 */
export class PracticeLoop {
  readonly #deps: PracticeLoopDeps;
  #line: LyricLine | null = null;
  #attempt = 0;
  /** Bumped on stop/restart: callbacks of an older run are ignored. */
  #run = 0;
  #unsubscribe: (() => void) | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;

  constructor(deps: PracticeLoopDeps) {
    this.#deps = deps;
  }

  get running(): boolean {
    return this.#line !== null;
  }

  /** Start practicing a line (stops any previous loop). */
  start(line: LyricLine): void {
    this.stop();
    this.#line = line;
    this.#attempt = 0;
    this.#play(this.#run);
  }

  stop(): void {
    this.#run++;
    this.#line = null;
    this.#release();
    this.#deps.playback.stop();
    this.#deps.onPhase({ name: "idle" });
  }

  #release(): void {
    this.#unsubscribe?.();
    this.#unsubscribe = null;
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }

  #play(run: number): void {
    const line = this.#line;
    if (line === null || run !== this.#run) return;
    const { playback, microphone, hopMs, onPhase, onVoice } = this.#deps;
    this.#attempt++;
    const attempt = this.#attempt;

    let sent = false;
    const finish = (sung: SungLine) => {
      if (sent || run !== this.#run) return;
      sent = true;
      this.#release();
      void this.#score(run, attempt, sung);
    };
    const collector = new LineCollector([line], hopMs, finish);
    this.#unsubscribe = microphone.subscribe((frame) => {
      const songMs = playback.songTimeAt(frame.time);
      if (songMs < line.start_ms - COUNT_IN_MS) return;
      collector.add(songMs, frame.f0);
      onVoice?.(songMs, frame.f0);
    });

    const fromMs = Math.max(0, line.start_ms - COUNT_IN_MS);
    playback.start(
      () => {
        // Track ended before the tail was complete (e.g. last line).
        collector.flush();
      },
      { fromMs, durationMs: line.end_ms + LINE_TAIL_MS + OUTRO_MS - fromMs },
    );
    onPhase({ name: "playing", attempt });
  }

  async #score(run: number, attempt: number, sung: SungLine): Promise<void> {
    const { score, onPhase } = this.#deps;
    onPhase({ name: "scoring", attempt });
    try {
      const analysis = await score(sung);
      if (run !== this.#run) return;
      onPhase({ name: "result", attempt, analysis });
      this.#timer = setTimeout(() => {
        this.#timer = null;
        this.#play(run);
      }, PAUSE_MS);
    } catch (error) {
      if (run !== this.#run) return;
      this.#line = null;
      this.#deps.playback.stop();
      onPhase({
        name: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }
}
