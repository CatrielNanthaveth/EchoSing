import { describe, expect, it } from "vitest";

import { lyricLine } from "../test/factories";
import { LINE_TAIL_MS, LineCollector, type SungLine } from "./lineCollector";

const HOP = 10;

function collect(
  lines = [lyricLine(0, 1000, 1100, "uno"), lyricLine(1, 1200, 1300, "dos")],
  hop = HOP,
) {
  const sung: SungLine[] = [];
  const collector = new LineCollector(lines, hop, (line) => sung.push(line));
  return { collector, sung };
}

/** Feed frames every `hop` ms from `fromMs` (with a phase offset) to `toMs`. */
function feed(
  collector: LineCollector,
  fromMs: number,
  toMs: number,
  f0: (ms: number) => number,
  hop = HOP,
) {
  for (let ms = fromMs; ms < toMs; ms += hop) collector.add(ms, f0(ms));
}

describe("LineCollector", () => {
  it("emits each line after its tail, sampled from the line start", () => {
    const { collector, sung } = collect();

    feed(collector, 3, 1000 + 100 + LINE_TAIL_MS - 5, () => 220);
    expect(sung).toEqual([]); // the tail is not complete yet

    feed(collector, 1398, 1420, () => 220);
    expect(sung).toHaveLength(1);
    expect(sung[0]?.lineIndex).toBe(0);
    expect(sung[0]?.hopMs).toBe(HOP);
    expect(sung[0]?.f0Hz).toHaveLength((100 + LINE_TAIL_MS) / HOP);
    expect(sung[0]?.f0Hz.every((hz) => hz === 220)).toBe(true);
  });

  it("aligns frames to the line start", () => {
    const { collector, sung } = collect();

    // Pitch encodes the frame time: 0 before the line, then 100 + ms after it.
    feed(collector, 4, 2000, (ms) => (ms < 1000 ? 0 : 100 + ms - 1000));

    expect(sung[0]?.f0Hz.slice(0, 3)).toEqual([104, 114, 124]);
  });

  it("marks unvoiced frames and gaps as 0", () => {
    const { collector, sung } = collect();

    feed(collector, 0, 1050, (ms) => (ms < 1020 ? 0 : 200));
    feed(collector, 1150, 2000, () => -1); // 100 ms gap, then negative values

    const f0 = sung[0]?.f0Hz ?? [];
    expect(f0.slice(0, 2)).toEqual([0, 0]);
    expect(f0.slice(2, 5)).toEqual([200, 200, 200]);
    expect(f0.slice(6, 14).every((hz) => hz === 0)).toBe(true);
    expect(f0.at(-1)).toBe(0);
  });

  it("keeps fractional hops and rounds pitch to 0.1 Hz", () => {
    const hop = 512 / 48;
    const { collector, sung } = collect(undefined, hop);

    feed(collector, 0, 2000, () => 220.123_456, hop);

    expect(sung[0]?.hopMs).toBe(10.667);
    expect(sung[0]?.f0Hz.every((hz) => hz === 220.1)).toBe(true);
  });

  it("emits overlapping tails for back-to-back lines", () => {
    const { collector, sung } = collect([
      lyricLine(0, 1000, 1500, "uno"),
      lyricLine(1, 1500, 2000, "dos"),
    ]);

    feed(collector, 0, 3000, (ms) => (ms < 1500 ? 100 : 200));

    expect(sung.map((line) => line.lineIndex)).toEqual([0, 1]);
    // Line 0's tail holds the start of line 1.
    expect(sung[0]?.f0Hz.at(-1)).toBe(200);
    expect(sung[1]?.f0Hz[0]).toBe(200);
  });

  it("flushes started lines when the song ends, not unreached ones", () => {
    const { collector, sung } = collect();

    feed(collector, 0, 1250, () => 300);
    collector.flush();

    expect(sung.map((line) => line.lineIndex)).toEqual([0, 1]);
    expect(sung[1]?.f0Hz.slice(0, 5)).toEqual([300, 300, 300, 300, 300]);
    expect(sung[1]?.f0Hz.slice(6).every((hz) => hz === 0)).toBe(true);

    const second = collect();
    feed(second.collector, 0, 900, () => 300);
    second.collector.flush();
    expect(second.sung).toEqual([]);
  });

  it("caps very long lines at 6000 frames", () => {
    const { collector, sung } = collect([lyricLine(0, 0, 100_000, "larga")], 10);

    feed(collector, 0, 100_400, () => 220, 10);

    expect(sung[0]?.f0Hz).toHaveLength(6000);
  });
});
