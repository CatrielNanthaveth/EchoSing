import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { songDetail } from "../test/factories";
import { LyricsView } from "./LyricsView";

const { lines } = songDetail();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
});

afterEach(() => {
  vi.useRealTimers();
});

function playAt(timeMs: number) {
  let now = timeMs;
  const clock = () => now;
  const view = render(<LyricsView lines={lines} clock={clock} />);
  const moveTo = (nextMs: number) => {
    now = nextMs;
    act(() => {
      vi.advanceTimersToNextFrame();
    });
  };
  moveTo(timeMs);
  return { ...view, moveTo };
}

function sungWords(): string[] {
  return Array.from(screen.getByTestId("current-line").querySelectorAll(".sung")).map(
    (word) => word.textContent.trim(),
  );
}

describe("LyricsView", () => {
  it("shows the first lines before playing", () => {
    render(<LyricsView lines={lines} clock={null} />);

    expect(screen.getByTestId("current-line")).toHaveTextContent("Hola mundo");
    expect(screen.getByTestId("current-line")).not.toHaveClass("active");
    expect(screen.getByTestId("next-line")).toHaveTextContent("Segunda línea");
  });

  it("counts down to the first line", () => {
    const { moveTo } = playAt(1000);
    expect(screen.queryByText("3")).toBeNull(); // 4 s left: too early

    moveTo(2500);
    expect(screen.getByText("3")).toBeVisible();

    moveTo(4200);
    expect(screen.getByText("1")).toBeVisible();
  });

  it("lights the words as they start", () => {
    const { moveTo } = playAt(5000);
    expect(screen.getByTestId("current-line")).toHaveClass("active");
    expect(sungWords()).toEqual(["Hola"]);

    moveTo(6500);
    expect(sungWords()).toEqual(["Hola", "mundo"]);
  });

  it("moves to the next lines", () => {
    const { moveTo } = playAt(9000);
    expect(screen.getByTestId("current-line")).toHaveTextContent("Segunda línea");
    expect(screen.getByTestId("next-line")).toHaveTextContent("Tercera línea");

    moveTo(13_000);
    expect(screen.getByText("Fin de la letra")).toBeVisible();
  });
});
