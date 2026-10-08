import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FrameListener, Microphone } from "../audio/microphone";
import { BEEP_COUNT, BEEP_INTERVAL_S, calibrate } from "./run";

function fakeNode() {
  const node = {
    connect: vi.fn(() => node),
    start: vi.fn<(when: number) => void>(),
    stop: vi.fn(),
    frequency: { value: 0 },
    gain: {
      value: 1,
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
      exponentialRampToValueAtTime: vi.fn(),
    },
  };
  return node;
}

function fakeContext() {
  const oscillators: ReturnType<typeof fakeNode>[] = [];
  const context = {
    currentTime: 0,
    destination: {},
    createOscillator: () => {
      const node = fakeNode();
      oscillators.push(node);
      return node;
    },
    createGain: fakeNode,
  };
  return { context: context as unknown as AudioContext, oscillators };
}

function fakeMicrophone() {
  const listeners = new Set<FrameListener>();
  const microphone = {
    subscribe: (listener: FrameListener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  } as unknown as Microphone;
  return { microphone, listeners };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("calibrate", () => {
  it("plays the beeps, records and measures the latency", async () => {
    const { context, oscillators } = fakeContext();
    const { microphone, listeners } = fakeMicrophone();
    const onScheduled = vi.fn();

    const pending = calibrate(context, microphone, onScheduled);

    const beeps = onScheduled.mock.calls[0]?.[0] as number[];
    expect(beeps).toHaveLength(BEEP_COUNT);
    expect((beeps[1] ?? 0) - (beeps[0] ?? 0)).toBeCloseTo(BEEP_INTERVAL_S);
    expect(oscillators.map((node) => node.start.mock.calls[0]?.[0])).toEqual(beeps);

    // Claps 120 ms after each beep, over a quiet background.
    for (let i = 0; i < 700; i++) {
      const time = i / 100;
      const clap = beeps.some((beep) => time >= beep + 0.12 && time < beep + 0.17);
      for (const listener of listeners)
        listener({ time, rms: clap ? 0.3 : 0.002, f0: 0, clarity: 0 });
    }
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toMatchObject({ ok: true, latencyMs: 120 });
    expect(listeners.size).toBe(0);
  });
});
