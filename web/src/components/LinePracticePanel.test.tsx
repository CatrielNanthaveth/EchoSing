import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { lineAnalysis, linePractice } from "../test/factories";
import { LinePracticePanel } from "./LinePracticePanel";

function renderPanel() {
  render(<LinePracticePanel sessionId="session-1" lineIndex={0} />);
}

describe("LinePracticePanel", () => {
  it("shows advice, the chart and a table per word", async () => {
    const getLineAnalysis = vi.spyOn(api, "getLineAnalysis").mockResolvedValue(
      linePractice({
        analysis: lineAnalysis({
          pitch_offset_semitones: -0.8,
          timing_offset_ms: 150,
          aligned_midi: [56, 56, 56, 56, 56, 58, 58, 58, 58, null],
        }),
      }),
    );

    renderPanel();

    expect(await screen.findByText("Cantaste ~0,8 semitonos más grave.")).toBeVisible();
    expect(screen.getByText("Ibas ~150 ms atrasado.")).toBeVisible();
    expect(
      screen.getByRole("figure", { name: "Melodía y tu voz a lo largo del verso" }),
    ).toBeInTheDocument();
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "PalabraMelodíaTu vozDiferencia (semitonos)",
      "HolaA3G#3−1",
      "mundoB3A#3−1",
    ]);
    expect(getLineAnalysis).toHaveBeenCalledWith(
      "session-1",
      0,
      expect.any(AbortSignal),
    );
  });

  it("can correct the rhythm to show only the intonation", async () => {
    vi.spyOn(api, "getLineAnalysis").mockResolvedValue(linePractice());
    const user = userEvent.setup();
    renderPanel();

    const toggle = await screen.findByRole("checkbox", { name: /Corregir el ritmo/ });
    await user.click(toggle);

    expect(toggle).toBeChecked();
  });

  it.each([
    ["not_sung", "No cantaste este verso."],
    ["not_stored", "antes de que guardáramos las curvas"],
  ] as const)("explains when there is no analysis (%s)", async (status, text) => {
    vi.spyOn(api, "getLineAnalysis").mockResolvedValue(
      linePractice({ status, analysis: null }),
    );

    renderPanel();

    expect(await screen.findByText(new RegExp(text))).toBeVisible();
    expect(screen.queryByRole("figure")).toBeNull();
  });

  it("retries errors", async () => {
    const getLineAnalysis = vi
      .spyOn(api, "getLineAnalysis")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue(linePractice());
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Reintentar" }));

    expect(await screen.findByText("Entraste a tiempo.")).toBeVisible();
    expect(getLineAnalysis).toHaveBeenCalledTimes(2);
  });
});
