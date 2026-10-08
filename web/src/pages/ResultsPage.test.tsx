import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { LineReport, SessionResults } from "../api/types";
import { linePractice, songDetail } from "../test/factories";
import { ResultsPage } from "./ResultsPage";

function report(overrides: Partial<LineReport> & { line_index: number }): LineReport {
  return {
    text: `Verso ${overrides.line_index + 1}`,
    sung: true,
    scorable: true,
    score: 80,
    accuracy: 0.7,
    hit: true,
    ...overrides,
  };
}

function results(overrides: Partial<SessionResults> = {}): SessionResults {
  return {
    session_id: "session-1",
    song_id: "song-1",
    analysis_id: "analysis-1",
    player_name: "Ana",
    difficulty: "easy",
    status: "finished",
    started_at: "2026-10-08T12:00:00Z",
    finished_at: "2026-10-08T12:03:35Z",
    totals: {
      total_score: 72.6,
      accuracy: 0.614,
      best_streak: 2,
      scored_lines: 4,
      hit_lines: 2,
    },
    lines: [
      report({ line_index: 0, score: 91.2 }),
      report({ line_index: 1, score: 85 }),
      report({ line_index: 2, score: 31.5, hit: false }),
      report({ line_index: 3, sung: false, score: 0, accuracy: 0, hit: false }),
      report({
        line_index: 4,
        scorable: false,
        score: null,
        accuracy: null,
        hit: false,
      }),
    ],
    ...overrides,
  };
}

function renderResults() {
  render(
    <MemoryRouter initialEntries={["/sessions/session-1/results"]}>
      <Routes>
        <Route path="/sessions/:sessionId/results" element={<ResultsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ResultsPage", () => {
  it("shows the totals of the session", async () => {
    const getResults = vi.spyOn(api, "getSessionResults").mockResolvedValue(results());
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());

    renderResults();

    expect(await screen.findByRole("heading", { name: "Chachacha" })).toBeVisible();
    expect(screen.getByText("Ana · Fácil")).toBeVisible();
    expect(screen.getByLabelText("Puntaje total")).toHaveTextContent("73");
    expect(screen.getByText("Afinación").nextSibling).toHaveTextContent("61%");
    expect(screen.getByText("Versos acertados").nextSibling).toHaveTextContent(
      "2 de 4",
    );
    expect(screen.getByText("Mejor racha").nextSibling).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "Cantar de nuevo" })).toHaveAttribute(
      "href",
      "/songs/song-1",
    );
    expect(getResults).toHaveBeenCalledWith("session-1", expect.any(AbortSignal));
  });

  it("lists every line: scored, unsung and not scorable", async () => {
    vi.spyOn(api, "getSessionResults").mockResolvedValue(results());
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());

    renderResults();

    const items = within(await screen.findByRole("list")).getAllByRole("listitem");
    expect(
      items.map((item) =>
        Array.from(item.querySelectorAll(".results-line-text, .results-line-score"))
          .map((cell) => cell.textContent)
          .join(" "),
      ),
    ).toEqual([
      "Verso 1 91",
      "Verso 2 85",
      "Verso 3 32",
      "Verso 4 no cantado",
      "Verso 5 no puntúa",
    ]);
    expect(items[0]).toHaveClass("hit");
    expect(items[2]).toHaveClass("miss");
    expect(items[3]).toHaveClass("unsung");
    expect(items[4]).toHaveClass("neutral");
  });

  it("opens how each sung line was sung", async () => {
    vi.spyOn(api, "getSessionResults").mockResolvedValue(results());
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    const getLineAnalysis = vi
      .spyOn(api, "getLineAnalysis")
      .mockResolvedValue(linePractice({ line_index: 2 }));
    const user = userEvent.setup();
    renderResults();

    const items = within(await screen.findByRole("list")).getAllByRole("listitem");
    const [, , third, fourth] = items;
    if (third === undefined || fourth === undefined) throw new Error("Missing lines");
    // Only sung lines can be opened.
    expect(within(fourth).queryByRole("button")).toBeNull();
    const toggle = within(third).getByRole("button", {
      name: "Ver cómo cantaste",
    });
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Entraste a tiempo.")).toBeVisible();
    expect(getLineAnalysis).toHaveBeenCalledWith(
      "session-1",
      2,
      expect.any(AbortSignal),
    );

    await user.click(screen.getByRole("button", { name: "Ocultar" }));
    expect(screen.queryByText("Entraste a tiempo.")).toBeNull();
  });

  it("marks unfinished sessions, without results for unsung lines", async () => {
    vi.spyOn(api, "getSessionResults").mockResolvedValue(
      results({
        status: "active",
        totals: {
          total_score: null,
          accuracy: null,
          best_streak: 0,
          scored_lines: 0,
          hit_lines: 0,
        },
        lines: [
          report({
            line_index: 0,
            sung: false,
            scorable: null,
            score: null,
            hit: false,
          }),
        ],
      }),
    );
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());

    renderResults();

    expect(await screen.findByText("Ana · Fácil · sesión sin terminar")).toBeVisible();
    expect(screen.getByLabelText("Puntaje total")).toHaveTextContent("–");
    expect(screen.getByText("Afinación").nextSibling).toHaveTextContent("–");
    expect(screen.getByRole("listitem")).toHaveTextContent("Verso 1–");
  });

  it("works without the song title", async () => {
    vi.spyOn(api, "getSessionResults").mockResolvedValue(results());
    vi.spyOn(api, "getSong").mockRejectedValue(new ApiError(404, "gone"));

    renderResults();

    expect(await screen.findByRole("heading", { name: "Resultados" })).toBeVisible();
  });

  it("shows not found for unknown sessions", async () => {
    vi.spyOn(api, "getSessionResults").mockRejectedValue(new ApiError(404, "nope"));

    renderResults();

    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeVisible();
  });

  it("retries other errors", async () => {
    vi.spyOn(api, "getSessionResults")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue(results());
    vi.spyOn(api, "getSong").mockResolvedValue(songDetail());
    const user = userEvent.setup();
    renderResults();

    await user.click(await screen.findByRole("button", { name: "Reintentar" }));

    expect(await screen.findByRole("heading", { name: "Chachacha" })).toBeVisible();
  });
});
