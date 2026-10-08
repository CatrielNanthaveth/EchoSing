import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { ApiError, api } from "../api/client";
import { getAudioContext, loadTrack } from "../audio/context";
import { Microphone, type FrameListener } from "../audio/microphone";
import { songDetail } from "../test/factories";
import { SongPage } from "./SongPage";

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

let sources: FakeSource[] = [];
let listeners: Set<FrameListener>;
let openMicrophone: MockInstance<typeof Microphone.open>;
const closeMicrophone = vi.fn();

beforeEach(() => {
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
    close: closeMicrophone,
  } as unknown as Microphone);
});

function renderSong() {
  return render(
    <MemoryRouter initialEntries={["/songs/song-1"]}>
      <Routes>
        <Route path="/songs/:songId" element={<SongPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function startSinging() {
  vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
  const user = userEvent.setup();
  const view = renderSong();
  await user.click(await screen.findByRole("button", { name: "Cantar" }));
  await screen.findByRole("button", { name: "Detener" });
  return { user, ...view };
}

/** Send microphone frames every 10 ms of context time (playback starts at 0.1 s). */
function sing(fromS: number, toS: number, f0: number) {
  act(() => {
    for (let time = fromS; time < toS; time += 0.01) {
      for (const listener of listeners) listener({ time, rms: 0.1, f0, clarity: 0.9 });
    }
  });
}

describe("SongPage", () => {
  it("shows the song and its first lines", async () => {
    const getSong = vi.spyOn(api, "getSong").mockResolvedValue(songDetail());

    renderSong();

    expect(await screen.findByRole("heading", { name: "Chachacha" })).toBeVisible();
    expect(screen.getByText("Josean Log")).toBeVisible();
    expect(screen.getByTestId("current-line")).toHaveTextContent("Hola mundo");
    expect(screen.getByText("1:00")).toBeVisible(); // duration
    expect(getSong).toHaveBeenCalledWith("song-1", expect.any(AbortSignal));
  });

  it("opens the microphone, downloads the track once and plays it", async () => {
    const { user } = await startSinging();

    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(loadTrack).toHaveBeenCalledWith(
      expect.anything(),
      "http://localhost:8000/songs/song-1/instrumental",
      expect.any(AbortSignal),
    );
    expect(sources[0]?.start).toHaveBeenCalled();
    expect(screen.getByLabelText("Micrófono")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Detener" }));
    expect(sources[0]?.stop).toHaveBeenCalled();
    expect(listeners.size).toBe(1); // capture stopped; only the live meter listens

    await user.click(screen.getByRole("button", { name: "Cantar" }));
    await screen.findByRole("button", { name: "Detener" });
    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(loadTrack).toHaveBeenCalledOnce();
    expect(sources).toHaveLength(2);
  });

  it("captures the pitch of each line", async () => {
    await startSinging();

    // Line 0 spans 5.0-7.3 s of song time with its tail: sing 1 s of it.
    sing(0.1, 5.1, 0);
    sing(5.1, 6.1, 220);
    sing(6.1, 7.5, 0);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Verso 1: voz detectada en 44%",
    );
  });

  it("offers to sing again when the song ends", async () => {
    await startSinging();

    act(() => {
      sources[0]?.onended?.();
    });

    expect(
      await screen.findByRole("button", { name: "Cantar de nuevo" }),
    ).toBeVisible();
    expect(listeners.size).toBe(1); // capture stopped; only the live meter listens
  });

  it("closes the microphone when leaving", async () => {
    const { unmount } = await startSinging();

    unmount();

    expect(closeMicrophone).toHaveBeenCalled();
    expect(sources[0]?.stop).toHaveBeenCalled();
  });

  it("reports microphone errors", async () => {
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    openMicrophone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Cantar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permiso de micrófono denegado",
    );
    expect(loadTrack).not.toHaveBeenCalled();
  });

  it("reports download errors", async () => {
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    vi.mocked(loadTrack).mockRejectedValue(new Error("HTTP 404"));
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Cantar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo empezar: HTTP 404",
    );
  });

  it("shows not found for unknown songs", async () => {
    vi.spyOn(api, "getSong").mockRejectedValue(new ApiError(404, "Not found"));

    renderSong();

    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeVisible();
  });

  it("retries other loading errors", async () => {
    const getSong = vi
      .spyOn(api, "getSong")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue(songDetail());
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Reintentar" }));

    expect(await screen.findByRole("heading", { name: "Chachacha" })).toBeVisible();
    expect(getSong).toHaveBeenCalledTimes(2);
  });
});
