import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { getAudioContext } from "../audio/context";
import { Microphone } from "../audio/microphone";
import { calibrate } from "../calibration/run";
import { loadLatency } from "../settings/latency";
import { CalibrationPage } from "./CalibrationPage";

vi.mock("../audio/context", () => ({ getAudioContext: vi.fn() }));
vi.mock("../calibration/run", () => ({ BEEP_COUNT: 8, calibrate: vi.fn() }));

const close = vi.fn();
let openMicrophone: MockInstance<typeof Microphone.open>;

beforeEach(() => {
  localStorage.clear();
  vi.mocked(getAudioContext).mockReturnValue({
    currentTime: 0,
    resume: () => Promise.resolve(),
  } as unknown as AudioContext);
  openMicrophone = vi
    .spyOn(Microphone, "open")
    .mockResolvedValue({ close } as unknown as Microphone);
});

function renderPage() {
  return render(
    <MemoryRouter>
      <CalibrationPage />
    </MemoryRouter>,
  );
}

describe("CalibrationPage", () => {
  it("measures and saves the latency", async () => {
    vi.mocked(calibrate).mockResolvedValue({
      ok: true,
      latencyMs: 142,
      matched: 8,
      spreadMs: 6,
    });
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByText("Latencia guardada: sin calibrar")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Empezar" }));

    expect(await screen.findByText("142 ms")).toBeVisible();
    expect(screen.getByText("8 de 8 golpes, ±6 ms")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Usar esta latencia" }));
    expect(loadLatency()).toBe(142);
    expect(screen.getByText("Latencia guardada: 142 ms")).toBeVisible();
    expect(screen.getByRole("button", { name: "En uso" })).toBeDisabled();
  });

  it("explains failed measurements and lets the player repeat", async () => {
    vi.mocked(calibrate).mockResolvedValue({
      ok: false,
      reason: "no_signal",
      matched: 2,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Empezar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("pocos golpes");
    expect(screen.getByRole("button", { name: "Repetir" })).toBeVisible();
  });

  it("reports microphone errors", async () => {
    openMicrophone.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Empezar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Permiso de micrófono denegado",
    );
  });

  it("opens the microphone once and closes it when leaving", async () => {
    vi.mocked(calibrate).mockResolvedValue({
      ok: false,
      reason: "no_signal",
      matched: 0,
    });
    const user = userEvent.setup();
    const { unmount } = renderPage();

    await user.click(screen.getByRole("button", { name: "Empezar" }));
    await user.click(await screen.findByRole("button", { name: "Repetir" }));
    await screen.findByRole("button", { name: "Repetir" });
    unmount();

    expect(openMicrophone).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  it("accepts a manual value", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("Ajustar a mano"));
    const input = screen.getByRole("spinbutton", { name: "Latencia (ms)" });
    await user.clear(input);
    await user.type(input, "95");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(loadLatency()).toBe(95);
    expect(screen.getByText("Latencia guardada: 95 ms")).toBeVisible();
  });
});
