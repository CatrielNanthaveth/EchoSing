import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FrameListener, Microphone } from "../audio/microphone";
import { MicTest } from "./MicTest";

let listeners: Set<FrameListener>;
const setDiagnostics = vi.fn();

function fakeMicrophone(): Microphone {
  return {
    subscribe: (listener: FrameListener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setDiagnostics,
  } as unknown as Microphone;
}

/** Emit 100 frames: `voiced` with pitch, the rest too quiet. */
function emit(voiced: number) {
  act(() => {
    for (let i = 0; i < 100; i++) {
      const sung = i < voiced;
      for (const listener of listeners) {
        listener({
          time: i / 100,
          rms: 0.05,
          f0: sung ? 220 : 0,
          clarity: sung ? 0.95 : 0,
          windowRms: sung ? 0.1 : 0.001,
          gated: !sung,
        });
      }
    }
  });
}

beforeEach(() => {
  listeners = new Set();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MicTest", () => {
  it("guides the player through the steps and reports what was detected", async () => {
    const getMicrophone = vi.fn(() => Promise.resolve(fakeMicrophone()));
    render(<MicTest getMicrophone={getMicrophone} />);

    act(() => {
      screen.getByRole("button", { name: "Probar micrófono" }).click();
    });
    expect(await screen.findByText(/Sostené una nota.* en 3…/)).toBeVisible();
    emit(100); // ignored: nothing is recorded during the countdown
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByText(/¡Ahora! Sostené una nota/)).toBeVisible();
    emit(90);
    await act(() => vi.advanceTimersByTimeAsync(4000));

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByText(/¡Ahora! Cantá una frase/)).toBeVisible();
    emit(50);
    await act(() => vi.advanceTimersByTimeAsync(6000));

    expect(
      await screen.findByText("Solo se detectó tu voz en el 50% del tiempo."),
    ).toBeVisible();
    expect(screen.getByText(/te capta bajo/)).toBeVisible();
    const detected = screen.getByRole("row", { name: /^Voz detectada \d/ });
    expect(
      within(detected)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["90%", "50%"]);
    expect(listeners.size).toBe(0);
    expect(setDiagnostics.mock.calls).toEqual([[true], [false]]);
    expect(screen.getByRole("row", { name: /Nota media/ })).toHaveTextContent(
      "A3 (220 Hz)",
    );
    expect(screen.getByRole("button", { name: "Repetir prueba" })).toBeVisible();
  });

  it("copies the results to share them", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<MicTest getMicrophone={() => Promise.resolve(fakeMicrophone())} />);

    act(() => {
      screen.getByRole("button", { name: "Probar micrófono" }).click();
    });
    await screen.findByText(/Sostené una nota/);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    emit(100);
    await act(() => vi.advanceTimersByTimeAsync(13_000));
    act(() => {
      screen.getByRole("button", { name: "Copiar resultados" }).click();
    });

    expect(await screen.findByRole("button", { name: "Copiado" })).toBeVisible();
    const copied = JSON.parse(writeText.mock.calls[0]?.[0] ?? "{}") as Record<
      string,
      { voicedShare: number }
    >;
    expect(copied.sustained?.voicedShare).toBe(1);
  });

  it("reports microphone errors", async () => {
    render(
      <MicTest
        getMicrophone={() =>
          Promise.reject(new DOMException("denied", "NotAllowedError"))
        }
      />,
    );

    act(() => {
      screen.getByRole("button", { name: "Probar micrófono" }).click();
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Permiso de micrófono");
  });
});
