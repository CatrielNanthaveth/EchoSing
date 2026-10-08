import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../api/client";
import { getAudioContext, loadTrack } from "../audio/context";
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

beforeEach(() => {
  sources = [];
  vi.mocked(getAudioContext).mockReturnValue({
    currentTime: 0,
    destination: {},
    resume: () => Promise.resolve(),
    createBufferSource: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
  } as unknown as AudioContext);
  vi.mocked(loadTrack).mockResolvedValue({ duration: 60 } as AudioBuffer);
});

function renderSong() {
  render(
    <MemoryRouter initialEntries={["/songs/song-1"]}>
      <Routes>
        <Route path="/songs/:songId" element={<SongPage />} />
      </Routes>
    </MemoryRouter>,
  );
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

  it("downloads the track once and plays and stops it", async () => {
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Reproducir" }));
    expect(await screen.findByRole("button", { name: "Detener" })).toBeVisible();
    expect(loadTrack).toHaveBeenCalledWith(
      expect.anything(),
      "http://localhost:8000/songs/song-1/instrumental",
      expect.any(AbortSignal),
    );
    expect(sources[0]?.start).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Detener" }));
    expect(sources[0]?.stop).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reproducir" }));
    await screen.findByRole("button", { name: "Detener" });
    expect(loadTrack).toHaveBeenCalledOnce();
    expect(sources).toHaveLength(2);
  });

  it("offers to sing again when the song ends", async () => {
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    const user = userEvent.setup();
    renderSong();
    await user.click(await screen.findByRole("button", { name: "Reproducir" }));
    await screen.findByRole("button", { name: "Detener" });

    sources[0]?.onended?.();

    expect(
      await screen.findByRole("button", { name: "Cantar de nuevo" }),
    ).toBeVisible();
  });

  it("reports playback errors", async () => {
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    vi.mocked(loadTrack).mockRejectedValue(new Error("HTTP 404"));
    const user = userEvent.setup();
    renderSong();

    await user.click(await screen.findByRole("button", { name: "Reproducir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo reproducir: HTTP 404",
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
