import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { linePractice, rhythmAnalysis } from "../test/factories";
import { PracticeView } from "./LinePracticePanel";
import { RhythmView } from "./RhythmView";

const WORDS = [
  { text: "Hola", start_ms: 0, end_ms: 300 },
  { text: "mundo", start_ms: 300, end_ms: 700 },
];

describe("RhythmView", () => {
  it("shows advice, the attacks of both and a table per attack", () => {
    render(<RhythmView analysis={rhythmAnalysis()} words={WORDS} />);

    expect(screen.getByText("Clavaste 2 de 4 golpes a tiempo.")).toBeVisible();
    expect(
      screen.getByRole("figure", { name: "Golpes de la original y los tuyos" }),
    ).toBeInTheDocument();
    // Tooltips on every mark: 4 reference and 4 sung attacks.
    expect(screen.getByText("Golpe 4: 600 ms (te faltó)")).toBeInTheDocument();
    expect(screen.getByText("Tu golpe: 900 ms (de más)")).toBeInTheDocument();
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "GolpeOriginalVosDesfase",
      "10,00 s0,01 s+10 ms",
      "20,20 s0,27 s+70 ms",
      "30,40 s0,38 s−20 ms",
      "40,60 s—faltó",
    ]);
  });

  it("is what the results show for rap lines", () => {
    render(
      <PracticeView
        practice={linePractice({
          mode: "rhythm",
          analysis: null,
          rhythm: rhythmAnalysis(),
        })}
      />,
    );

    expect(screen.getByText("Clavaste 2 de 4 golpes a tiempo.")).toBeVisible();
    expect(screen.queryByRole("figure", { name: /Melodía/ })).toBeNull();
  });
});
