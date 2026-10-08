import type { LineDiagnostics } from "../api/types";
import { hzToMidi } from "./pitch";
import { chartRows, type ChartRow } from "./practice";

/** Words whose span has less voice than this in the original look out of sync. */
export const LOW_VOICING = 0.5;

/**
 * Practice chart rows plus what was sung *before* undoing the latency, in the
 * same octave as the voice curve, sampled at each row's time.
 */
export function diagnosticRows(
  diagnostics: LineDiagnostics,
  aligned: boolean,
): ChartRow[] {
  const { analysis, sung_input: input } = diagnostics;
  if (analysis === null) return [];
  const rows = chartRows(analysis, aligned);
  if (input === null) return rows;
  return rows.map((row) => {
    const hz = input.f0_hz[Math.round((row.timeS * 1000) / input.hop_ms)] ?? 0;
    return {
      ...row,
      rawVoice:
        hz > 0 ? Math.round((hzToMidi(hz) - analysis.octave_shift) * 100) / 100 : null,
    };
  });
}

/** Words that should be sung but have little voice in the original. */
export function suspiciousWords(diagnostics: LineDiagnostics) {
  return diagnostics.word_timing.filter((word) => word.voiced_ratio < LOW_VOICING);
}

/** Download the diagnostics as a JSON file. */
export function downloadJson(diagnostics: LineDiagnostics): void {
  const blob = new Blob([JSON.stringify(diagnostics, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `diagnostico-${diagnostics.session_id}-verso-${String(diagnostics.line_index + 1)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
