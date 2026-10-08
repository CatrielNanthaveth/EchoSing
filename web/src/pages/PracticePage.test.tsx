import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { ApiError, api } from "../api/client";
import type { PitchResponse } from "../api/types";
import { getAudioContext, loadTrack } from "../audio/context";
import { Microphone, type FrameListener } from "../audio/microphone";
import { saveDifficulty } from "../settings/difficulty";
import { saveLatency } from "../settings/latency";
import { lineAnalysis, songDetail } from "../test/factories";
import { PracticePage } from "./PracticePage";

vi.mock("../audio/context", () => ({
  getAudioContext: vi.fn(),
  loadTrack: vi.fn(),
  outputLatencyMs: () => 0,
}));

class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
}

const PITCH: PitchResponse = {
  analysis_id: "analysis-1",
  line_index: 0,
  start_ms: 5000,
  hop_ms: 10,
  midi: Array<number>(200).fill(57),
  confidence: Array<number>(200).fill(95),
};

let sources: FakeSource[];
let listeners: Set<FrameListener>;
let openMicrophone: MockInstance<typeof Microphone.open>;
let scoreAttempt: MockInstance<typeof api.scoreAttempt>;
let getPitch: MockInstance<typeof api.getPitch>;

beforeEach(() => {
  localStorage.clear();
  sources = [];
  listeners = new Set();
  vi.mocked(getAudioContext).mockReturnValue({
    currentTime: 0,
    sampleRate: 48_000,
    destination: {},
    resume: () => Promise.resolve(),
    createBufferSource: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
  } as unknown as AudioContext);
  vi.mocked(loadTrack).mockResolvedValue({ duration: 60 } as AudioBuffer);
  openMicrophone = vi.spyOn(Microphone, "open").mockResolvedValue({
    subscribe: (listener: FrameListener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    close: vi.fn(),
  } as unknown as Microphone);
  vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
  getPitch = vi.spyOn(api, "getPitch").mockResolvedValue(PITCH);
  scoreAttempt = vi
    .spyOn(api, "scoreAttempt")
    .mockResolvedValue(
      lineAnalysis({ result: { ...lineAnalysis().result, score: 87.6 } }),
    );
});

function renderPractice(path = "/songs/song-1/practica") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/songs/:songId/practica" element={<PracticePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * Microphone frames every 10 ms of context time. Line 1 ("Hola mundo")
 * spans 5-7 s; its segment starts at 3 s of song time, 0.1 s after
 * pressing play: song ms = (context s + 2.9) * 1000.
 */
function sing(fromS: number, toS: number, f0 = 220) {
  act(() => {
    for (let time = fromS; time < toS; time += 0.01) {
      for (const listener of listeners) {
        listener({ time, rms: 0.1, f0, clarity: 0.9, windowRms: 0.1, gated: false });
      }
    }
  });
}

describe("PracticePage", () => {
  it("lists the lines and opens the one in the URL", async () => {
    renderPractice("/songs/song-1/practica?verso=2");

    expect(await screen.findByRole("heading", { name: "Segunda línea" })).toBeVisible();
    expect(screen.getByRole("button", { name: /2\. Segunda línea/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(getPitch).toHaveBeenCalledWith("song-1", expect.any(AbortSignal), 1);
    expect(
      await screen.findByRole("img", { name: "Melodía del verso y tu voz en vivo" }),
    ).toBeInTheDocument();
  });

  it("plays the line, scores each attempt and keeps the history", async () => {
    saveLatency(50);
    saveDifficulty("easy");
    const user = userEvent.setup();
    renderPractice();

    await user.click(
      await screen.findByRole("button", { name: "Practicar este verso" }),
    );

    expect(await screen.findByText(/Escuchá la entrada/)).toBeVisible();
    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(sources[0]?.start).toHaveBeenCalledWith(0.1, 3, expect.closeTo(4.5, 5));

    sing(0, 4.6);

    expect(await screen.findByLabelText("Intentos")).toHaveTextContent("88");
    const [songId, line, attempt] = scoreAttempt.mock.calls[0] ?? [];
    expect([songId, line]).toEqual(["song-1", 0]);
    expect(attempt).toMatchObject({
      analysis_id: "analysis-1",
      hop_ms: 10.667,
      latency_offset_ms: 50,
      difficulty: "easy",
    });
    expect(screen.getByText("Entraste a tiempo.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Detener" }));
    expect(screen.getByRole("button", { name: "Practicar este verso" })).toBeVisible();
    expect(screen.getByLabelText("Intentos")).toHaveTextContent("88"); // kept
  });

  it("forgets the attempts when another line is chosen", async () => {
    const user = userEvent.setup();
    renderPractice();
    await user.click(
      await screen.findByRole("button", { name: "Practicar este verso" }),
    );
    sing(0, 4.6);
    await screen.findByLabelText("Intentos");

    const lines = screen.getByRole("navigation", { name: "Versos" });
    await user.click(within(lines).getByRole("button", { name: /3\. Tercera línea/ }));

    expect(await screen.findByRole("heading", { name: "Tercera línea" })).toBeVisible();
    expect(screen.queryByLabelText("Intentos")).toBeNull();
  });

  it("reports microphone errors", async () => {
    openMicrophone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const user = userEvent.setup();
    renderPractice();

    await user.click(
      await screen.findByRole("button", { name: "Practicar este verso" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permiso de micrófono denegado",
    );
  });

  it("shows not found for unknown songs", async () => {
    vi.spyOn(api, "getSong").mockRejectedValue(new ApiError(404, "nope"));

    renderPractice();

    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeVisible();
  });
});
