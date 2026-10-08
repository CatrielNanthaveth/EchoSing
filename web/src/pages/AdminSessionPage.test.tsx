import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { SessionResults } from "../api/types";
import { saveAdminToken } from "../settings/adminToken";
import { lineDiagnostics } from "../test/factories";
import { AdminSessionPage } from "./AdminSessionPage";

const RESULTS: SessionResults = {
  session_id: "session-1",
  song_id: "song-1",
  analysis_id: "analysis-1",
  player_name: "Ana",
  difficulty: "normal",
  status: "finished",
  started_at: "2026-10-08T12:00:00Z",
  finished_at: "2026-10-08T12:03:00Z",
  totals: {
    total_score: 70,
    accuracy: 0.6,
    best_streak: 1,
    scored_lines: 2,
    hit_lines: 1,
  },
  lines: [
    {
      line_index: 0,
      text: "Intro",
      sung: false,
      scorable: true,
      score: 0,
      accuracy: 0,
      hit: false,
    },
    {
      line_index: 1,
      text: "Hola mundo",
      sung: true,
      scorable: true,
      score: 82,
      accuracy: 0.7,
      hit: true,
    },
    {
      line_index: 2,
      text: "Chau",
      sung: true,
      scorable: true,
      score: 40,
      accuracy: 0.3,
      hit: false,
    },
  ],
};

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "getSessionResults").mockResolvedValue(RESULTS);
});

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/admin/sesiones/session-1"]}>
      <Routes>
        <Route path="/admin/sesiones/:sessionId" element={<AdminSessionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminSessionPage", () => {
  it("asks for the admin token and remembers it", async () => {
    const getDiagnostics = vi
      .spyOn(api, "getLineDiagnostics")
      .mockResolvedValue(lineDiagnostics({ line_index: 1 }));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Clave de administrador"), "secret");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("heading", { name: /Verso 2/ })).toBeVisible();
    expect(getDiagnostics).toHaveBeenCalledWith(
      "session-1",
      1, // the first sung line
      "secret",
      expect.any(AbortSignal),
    );
    expect(localStorage.getItem("echosing.adminToken")).toBe("secret");
  });

  it("shows parameters, word timing and possible lyrics desync", async () => {
    saveAdminToken("secret");
    vi.spyOn(api, "getLineDiagnostics").mockResolvedValue(
      lineDiagnostics({ line_index: 1 }),
    );
    renderPage();

    expect(
      await screen.findByText(/Posible desfase de letra: mundo tiene/),
    ).toBeVisible();
    expect(screen.getByText("Diagnóstico · Ana · Normal · finished")).toBeVisible();
    expect(
      screen.getByText("Latencia compensada").nextElementSibling,
    ).toHaveTextContent("40 ms");
    expect(screen.getByText("Análisis").nextElementSibling).toHaveTextContent(
      "v2 · htdemucs · whisper-large-v3-turbo · torchcrepe-full",
    );
    expect(
      screen.getByText("Entrada del cliente").nextElementSibling,
    ).toHaveTextContent("10 frames cada 20 ms");
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows[2]).toHaveClass("suspicious");
    expect(rows[2]).toHaveTextContent("mundo100 ms200 ms20%—");
    expect(
      screen.getByRole("figure", { name: "Melodía y tu voz a lo largo del verso" }),
    ).toBeInTheDocument();
  });

  it("switches between lines", async () => {
    saveAdminToken("secret");
    const getDiagnostics = vi
      .spyOn(api, "getLineDiagnostics")
      .mockImplementation((_session, line) =>
        Promise.resolve(
          lineDiagnostics({ line_index: line, text: `Línea ${String(line)}` }),
        ),
      );
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /Verso 2/ });

    await user.click(screen.getByRole("button", { name: /3\. Chau/ }));

    expect(
      await screen.findByRole("heading", { name: "Verso 3: Línea 2" }),
    ).toBeVisible();
    expect(getDiagnostics).toHaveBeenLastCalledWith(
      "session-1",
      2,
      "secret",
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("button", { name: /3\. Chau/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("asks again when the token is rejected", async () => {
    saveAdminToken("old");
    vi.spyOn(api, "getLineDiagnostics").mockRejectedValue(new ApiError(401, "nope"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "La clave de administrador no es válida.",
    );
    expect(localStorage.getItem("echosing.adminToken")).toBeNull();
  });

  it("explains lines without a sung curve", async () => {
    saveAdminToken("secret");
    vi.spyOn(api, "getLineDiagnostics").mockResolvedValue(
      lineDiagnostics({ status: "not_stored", analysis: null, sung_input: null }),
    );
    renderPage();

    expect(await screen.findByText("Sin curva cantada para este verso.")).toBeVisible();
    expect(
      screen.getByText("Entrada del cliente").nextElementSibling,
    ).toHaveTextContent("no guardada");
  });

  it("shows not found for unknown sessions", async () => {
    saveAdminToken("secret");
    vi.spyOn(api, "getSessionResults").mockRejectedValue(new ApiError(404, "nope"));
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeVisible();
  });
});
