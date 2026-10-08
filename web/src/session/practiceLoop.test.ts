import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LineAnalysis } from "../api/types";
import type { FrameListener, Microphone } from "../audio/microphone";
import type { Playback } from "../audio/playback";
import { lineAnalysis, lyricLine } from "../test/factories";
import type { SungLine } from "./lineCollector";
import { COUNT_IN_MS, PAUSE_MS, PracticeLoop, type LoopPhase } from "./practiceLoop";

const LINE = lyricLine(3, 10_000, 11_000, "Hola mundo");
const HOP = 10;

function setup(
  score = vi.fn<(sung: SungLine) => Promise<LineAnalysis>>(() =>
    Promise.resolve(lineAnalysis()),
  ),
) {
  const listeners = new Set<FrameListener>();
  const microphone = {
    subscribe: (listener: FrameListener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  } as unknown as Microphone;
  let onEnded: (() => void) | undefined;
  const playback = {
    start: vi.fn((ended?: () => void) => {
      onEnded = ended;
    }),
    stop: vi.fn(),
    // Context time == song time in seconds, to keep the arithmetic simple.
    songTimeAt: (contextTime: number) => contextTime * 1000,
    startedAt: 0,
  };
  const phases: LoopPhase[] = [];
  const voice: [number, number][] = [];
  const loop = new PracticeLoop({
    playback: playback as unknown as Playback,
    microphone,
    hopMs: HOP,
    score,
    onPhase: (phase) => phases.push(phase),
    onVoice: (songMs, f0) => voice.push([songMs, f0]),
  });
  /** Microphone frames every 10 ms of song time. */
  const sing = (fromMs: number, toMs: number, f0 = 220) => {
    for (let ms = fromMs; ms < toMs; ms += HOP) {
      for (const listener of listeners) {
        listener({
          time: ms / 1000,
          rms: 0.1,
          f0,
          clarity: 0.9,
          windowRms: 0.1,
          gated: false,
        });
      }
    }
  };
  return {
    loop,
    playback,
    phases,
    voice,
    sing,
    score,
    listeners,
    ended: () => onEnded?.(),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("PracticeLoop", () => {
  it("plays the line with a count-in and scores what was sung", async () => {
    const { loop, playback, phases, sing, score, voice } = setup();

    loop.start(LINE);

    expect(playback.start).toHaveBeenCalledWith(expect.any(Function), {
      fromMs: 10_000 - COUNT_IN_MS,
      durationMs: COUNT_IN_MS + 1000 + 300 + 200,
    });
    expect(phases.at(-1)).toEqual({ name: "playing", attempt: 1 });

    sing(7000, 8000); // before the count-in: ignored
    sing(8000, 11_400);
    await vi.waitFor(() => {
      expect(phases.at(-1)?.name).toBe("result");
    });

    const sung = score.mock.calls[0]?.[0];
    expect(sung?.lineIndex).toBe(3);
    expect(sung?.f0Hz).toHaveLength((1000 + 300) / HOP);
    expect(voice[0]).toEqual([8000, 220]);
    expect(phases.map((phase) => phase.name)).toEqual([
      "idle",
      "playing",
      "scoring",
      "result",
    ]);
  });

  it("repeats after a pause, counting attempts", async () => {
    const { loop, playback, phases, sing } = setup();
    loop.start(LINE);
    sing(8000, 11_400);
    await vi.waitFor(() => {
      expect(phases.at(-1)?.name).toBe("result");
    });

    await vi.advanceTimersByTimeAsync(PAUSE_MS);

    expect(playback.start).toHaveBeenCalledTimes(2);
    expect(phases.at(-1)).toEqual({ name: "playing", attempt: 2 });
  });

  it("scores what there is when the track ends early", async () => {
    const { loop, phases, sing, score, ended } = setup();
    loop.start(LINE);
    sing(8000, 10_500);

    ended();

    await vi.waitFor(() => {
      expect(phases.at(-1)?.name).toBe("result");
    });
    expect(score).toHaveBeenCalledOnce();
  });

  it("stops: no more frames, results or repetitions", async () => {
    let resolve: (analysis: ReturnType<typeof lineAnalysis>) => void = () => undefined;
    const score = vi.fn(
      () =>
        new Promise<ReturnType<typeof lineAnalysis>>((done) => {
          resolve = done;
        }),
    );
    const { loop, playback, phases, sing, listeners } = setup(score);
    loop.start(LINE);
    sing(8000, 11_400);

    loop.stop();
    resolve(lineAnalysis());
    await vi.advanceTimersByTimeAsync(PAUSE_MS * 2);

    expect(loop.running).toBe(false);
    expect(listeners.size).toBe(0);
    expect(playback.stop).toHaveBeenCalled();
    expect(playback.start).toHaveBeenCalledOnce();
    expect(phases.at(-1)).toEqual({ name: "idle" });
  });

  it("stops looping on scoring errors", async () => {
    const { loop, phases, sing } = setup(
      vi.fn(() => Promise.reject(new Error("HTTP 500"))),
    );
    loop.start(LINE);
    sing(8000, 11_400);

    await vi.waitFor(() => {
      expect(phases.at(-1)).toEqual({ name: "error", message: "HTTP 500" });
    });
    expect(loop.running).toBe(false);
  });

  it("runs a hook with each attempt, at the line start, and cleans it up", () => {
    const stopGuide = vi.fn();
    const onAttemptStart = vi.fn(() => stopGuide);
    const loop = new PracticeLoop({
      playback: {
        start: vi.fn(),
        stop: vi.fn(),
        songTimeAt: (t: number) => t * 1000,
        startedAt: 2, // song time 0 plays at context time 2 s
      } as unknown as Playback,
      microphone: { subscribe: () => () => undefined } as unknown as Microphone,
      hopMs: HOP,
      score: () => Promise.resolve(lineAnalysis()),
      onPhase: () => undefined,
      onAttemptStart,
    });

    loop.start(LINE);
    expect(onAttemptStart).toHaveBeenCalledWith(2 + 10);

    loop.stop();
    expect(stopGuide).toHaveBeenCalledOnce();
  });
});
