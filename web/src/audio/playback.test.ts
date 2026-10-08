import { describe, expect, it, vi } from "vitest";

import { Playback } from "./playback";

class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn(() => {
    this.onended?.();
  });
}

function fakeContext() {
  const sources: FakeSource[] = [];
  const context = {
    currentTime: 10,
    destination: { name: "speakers" },
    createBufferSource: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
  };
  return { context, sources };
}

function playback() {
  const { context, sources } = fakeContext();
  const buffer = { duration: 180 } as AudioBuffer;
  return {
    context,
    sources,
    player: new Playback(context as unknown as BaseAudioContext, buffer),
  };
}

describe("Playback", () => {
  it("starts slightly ahead and reports the song position from the context clock", () => {
    const { context, sources, player } = playback();

    player.start();

    const source = sources[0];
    expect(source?.connect).toHaveBeenCalledWith(context.destination);
    expect(source?.start).toHaveBeenCalledWith(10.1);
    expect(player.playing).toBe(true);
    expect(player.durationMs).toBe(180_000);
    expect(player.positionMs()).toBe(0); // before the first sample

    context.currentTime = 12.6;
    expect(player.positionMs()).toBeCloseTo(2500);
    expect(player.songTimeAt(11.1)).toBeCloseTo(1000);
  });

  it("calls onEnded when the track finishes", () => {
    const { sources, player } = playback();
    const onEnded = vi.fn();

    player.start(onEnded);
    sources[0]?.onended?.();

    expect(onEnded).toHaveBeenCalledOnce();
    expect(player.playing).toBe(false);
    expect(player.positionMs()).toBe(0);
  });

  it("does not call onEnded when stopped or restarted", () => {
    const { sources, player } = playback();
    const onEnded = vi.fn();

    player.start(onEnded);
    player.start(onEnded); // restart stops the first source
    player.stop();
    player.stop(); // no-op

    expect(onEnded).not.toHaveBeenCalled();
    expect(sources).toHaveLength(2);
    expect(sources[0]?.disconnect).toHaveBeenCalled();
    expect(player.playing).toBe(false);
  });

  it("plays a segment and keeps song times right", () => {
    const { context, sources, player } = playback();

    player.start(undefined, { fromMs: 30_000, durationMs: 5000 });

    expect(sources[0]?.start).toHaveBeenCalledWith(10.1, 30, 5);
    context.currentTime = 11.1; // 1 s into the segment
    expect(player.positionMs()).toBeCloseTo(31_000);
    expect(player.songTimeAt(12.1)).toBeCloseTo(32_000);
  });
});
