import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { ApiError, api } from "../api/client";
import type { SessionCreated } from "../api/types";
import { getAudioContext, loadTrack } from "../audio/context";
import { Microphone, type FrameListener } from "../audio/microphone";
import { saveLatency } from "../settings/latency";
import {
  FakeSocket,
  SUMMARY_MESSAGE,
  lastSocket,
  lineScoreMessage,
  readyMessage,
} from "../test/fakeSocket";
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

const CREATED: SessionCreated = {
  session_id: "session-1",
  song_id: "song-1",
  analysis_id: "analysis-1",
  analysis_version: 1,
  line_count: 3,
  player_name: "Ana",
  latency_offset_ms: 120,
};

let sources: FakeSource[] = [];
let listeners: Set<FrameListener>;
let openMicrophone: MockInstance<typeof Microphone.open>;
let createSession: MockInstance<typeof api.createSession>;
const closeMicrophone = vi.fn();

beforeEach(() => {
  localStorage.clear();
  sources = [];
  listeners = new Set();
  FakeSocket.instances.length = 0;
  vi.stubGlobal(
    "WebSocket",
    Object.assign(FakeSocket, { CONNECTING: 0, OPEN: 1, CLOSED: 3 }),
  );
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
  createSession = vi.spyOn(api, "createSession").mockResolvedValue(CREATED);
  vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
});

function renderSong() {
  return render(
    <MemoryRouter initialEntries={["/songs/song-1"]}>
      <Routes>
        <Route path="/songs/:songId" element={<SongPage />} />
        <Route
          path="/sessions/:sessionId/results"
          element={<p>Resultados de la sesión</p>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

async function startSinging() {
  const user = userEvent.setup();
  const view = renderSong();
  await user.click(await screen.findByRole("button", { name: "Cantar" }));
  await screen.findByRole("button", { name: "Detener" });
  const socket = lastSocket();
  act(() => {
    socket.receive(readyMessage());
  });
  return { user, socket, ...view };
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
  it("shows the song, the player name and the latency to calibrate", async () => {
    renderSong();

    expect(await screen.findByRole("heading", { name: "Chachacha" })).toBeVisible();
    expect(screen.getByText("Josean Log")).toBeVisible();
    expect(screen.getByTestId("current-line")).toHaveTextContent("Hola mundo");
    expect(screen.getByText("1:00")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Tu nombre" })).toHaveValue("Jugador");
    expect(screen.getByRole("link", { name: "calibrala" })).toHaveAttribute(
      "href",
      "/calibrar",
    );
  });

  it("starts a session with the player name and calibrated latency", async () => {
    saveLatency(120);
    const user = userEvent.setup();
    renderSong();
    expect(await screen.findByText(/Latencia: 120 ms/)).toBeVisible();

    const name = screen.getByRole("textbox", { name: "Tu nombre" });
    await user.clear(name);
    await user.type(name, " Ana ");
    await user.click(screen.getByRole("button", { name: "Cantar" }));

    await screen.findByRole("button", { name: "Detener" });
    expect(createSession).toHaveBeenCalledWith({
      song_id: "song-1",
      player_name: "Ana",
      latency_offset_ms: 120,
    });
    expect(FakeSocket.instances[0]?.url).toBe(
      "ws://localhost:8000/ws/sessions/session-1",
    );
    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(loadTrack).toHaveBeenCalledWith(
      expect.anything(),
      "http://localhost:8000/songs/song-1/instrumental",
      expect.any(AbortSignal),
    );
    expect(sources[0]?.start).toHaveBeenCalled();
    expect(screen.getByLabelText("Micrófono")).toBeVisible();
  });

  it("sends each sung line and shows its score", async () => {
    const { socket } = await startSinging();

    // Line 0 spans 5.0-7.3 s of song time with its tail: sing 1 s of it.
    sing(0.1, 5.1, 0);
    sing(5.1, 6.1, 220);
    sing(6.1, 7.5, 0);

    const [message] = socket.sent;
    expect(message).toMatchObject({
      type: "line_pitch",
      line_index: 0,
      hop_ms: 10.667,
    });
    const f0 = message?.type === "line_pitch" ? message.f0_hz : [];
    expect(f0.filter((hz) => hz === 220)).toHaveLength(94);

    act(() => {
      socket.receive(lineScoreMessage(0, { score: 91.6, streak: 3 }));
    });
    const card = screen.getByRole("status", { name: "Puntaje del verso" });
    expect(card).toHaveTextContent("92");
    expect(card).toHaveTextContent("¡Excelente!");
    expect(card).toHaveTextContent("Racha ×3");
  });

  it.each([
    [{ score: 70, hit: true }, "¡Bien!"],
    [{ score: 40, hit: false }, "Casi…"],
    [{ score: 5, hit: false }, "Fuera de tono"],
    [{ scorable: false, score: null, hit: false }, "no puntúa"],
  ])("explains a line score of %j", async (score, verdict) => {
    const { socket } = await startSinging();

    act(() => {
      socket.receive(lineScoreMessage(1, score));
    });

    expect(screen.getByRole("status", { name: "Puntaje del verso" })).toHaveTextContent(
      verdict,
    );
  });

  it("finishes the session when the song ends and opens its results", async () => {
    const { socket } = await startSinging();

    act(() => {
      sources[0]?.onended?.();
    });
    expect(socket.sent.at(-1)).toEqual({ type: "finish" });
    expect(screen.getByText("Calculando el resultado…")).toBeVisible();
    expect(listeners.size).toBe(0);

    act(() => {
      socket.receive(SUMMARY_MESSAGE);
    });

    expect(await screen.findByText("Resultados de la sesión")).toBeVisible();
    expect(closeMicrophone).toHaveBeenCalled();
  });

  it("abandons the session when the player stops", async () => {
    const { user, socket } = await startSinging();

    await user.click(screen.getByRole("button", { name: "Detener" }));

    expect(sources[0]?.stop).toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalled();
    expect(socket.sent).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Cantar" }));
    await screen.findByRole("button", { name: "Detener" });
    expect(createSession).toHaveBeenCalledTimes(2);
    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(loadTrack).toHaveBeenCalledOnce();
  });

  it("warns when the connection is lost", async () => {
    const { socket } = await startSinging();

    act(() => {
      socket.drop(4409);
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Se perdió la conexión");
  });

  it("closes the microphone and the session when leaving", async () => {
    const { socket, unmount } = await startSinging();

    unmount();

    expect(closeMicrophone).toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalled();
    expect(sources[0]?.stop).toHaveBeenCalled();
  });

  it("reports microphone errors and drops the session", async () => {
    openMicrophone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Cantar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permiso de micrófono denegado",
    );
    expect(FakeSocket.instances[0]?.close).toHaveBeenCalled();
    expect(loadTrack).not.toHaveBeenCalled();
  });

  it("reports session errors without playing", async () => {
    createSession.mockRejectedValue(new ApiError(404, "Song song-1 is not available"));
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Cantar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo crear la sesión: Song song-1 is not available",
    );
    expect(openMicrophone).not.toHaveBeenCalled();
  });

  it("asks to reload when the song was reprocessed meanwhile", async () => {
    createSession.mockResolvedValue({ ...CREATED, analysis_id: "analysis-2" });
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Cantar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Recargá la página");
    expect(FakeSocket.instances).toHaveLength(0);
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
