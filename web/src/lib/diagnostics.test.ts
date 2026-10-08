import { afterEach, describe, expect, it, vi } from "vitest";

import { lineAnalysis, lineDiagnostics } from "../test/factories";
import { diagnosticRows, downloadJson, suspiciousWords } from "./diagnostics";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("diagnosticRows", () => {
  it("adds the voice before undoing the latency", () => {
    const rows = diagnosticRows(lineDiagnostics(), false);

    expect(rows[0]).toMatchObject({ timeS: 0, reference: 57, rawVoice: null });
    expect(rows[1]).toMatchObject({ timeS: 0.02, rawVoice: 57 });
  });

  it("moves the raw voice to the octave shown for the voice", () => {
    const rows = diagnosticRows(
      lineDiagnostics({ analysis: lineAnalysis({ octave_shift: -12 }) }),
      false,
    );

    expect(rows[1]?.rawVoice).toBe(69);
  });

  it("has no raw voice when the input was not stored", () => {
    const rows = diagnosticRows(lineDiagnostics({ sung_input: null }), true);

    expect(rows[1]).not.toHaveProperty("rawVoice");
  });

  it("is empty without an analysis", () => {
    expect(diagnosticRows(lineDiagnostics({ analysis: null }), false)).toEqual([]);
  });
});

describe("suspiciousWords", () => {
  it("flags words with little voice in the original", () => {
    expect(suspiciousWords(lineDiagnostics()).map((word) => word.text)).toEqual([
      "mundo",
    ]);
  });
});

describe("downloadJson", () => {
  it("downloads the diagnostics as a named JSON file", () => {
    const createObjectURL = vi.fn(() => "blob:diagnostics");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    downloadJson(lineDiagnostics());

    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("diagnostico-session-1-verso-1.json");
    expect(anchor.href).toBe("blob:diagnostics");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:diagnostics");
  });
});
