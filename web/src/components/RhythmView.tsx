import type { PracticeWord } from "../api/types";
import { SERIES_COLORS } from "../lib/chartColors";
import { attackRows, rhythmAdvice, type RhythmAnalysis } from "../lib/rhythm";

const GRID = "#2a2f3c";
const MUTED = "#9097a8";
const HEIGHT = 150;
const LEFT = 64;
const RIGHT = 12;
const WIDTH = 720;
const ROWS = { reference: 52, voice: 112 };

function formatOffset(ms: number): string {
  if (Math.round(ms) === 0) return "0 ms";
  return `${ms > 0 ? "+" : "−"}${String(Math.round(Math.abs(ms)))} ms`;
}

/**
 * Syllable attacks of the original (top row) and the singer (bottom row),
 * joined when they were paired. Hollow marks: missed or extra attacks.
 */
export function RhythmChart({
  analysis,
  words,
}: {
  analysis: RhythmAnalysis;
  words: readonly PracticeWord[];
}) {
  const lastMs = Math.max(
    ...analysis.reference_onsets_ms,
    ...analysis.sung_onsets_ms,
    ...words.map((word) => word.end_ms),
    1,
  );
  const x = (ms: number) => LEFT + (ms / lastMs) * (WIDTH - LEFT - RIGHT);
  const paired = new Set(analysis.pairs.map((pair) => pair.sung));
  const matched = new Set(analysis.pairs.map((pair) => pair.reference));

  return (
    <figure className="rhythm-chart" aria-label="Golpes de la original y los tuyos">
      <svg viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img">
        {words.map((word) => (
          <g key={`${word.text}-${String(word.start_ms)}`}>
            <line
              x1={x(word.start_ms)}
              x2={x(word.start_ms)}
              y1={18}
              y2={HEIGHT - 16}
              stroke={GRID}
            />
            <text x={x(word.start_ms) + 3} y={12} fill={MUTED} fontSize={11}>
              {word.text}
            </text>
          </g>
        ))}
        <text x={4} y={ROWS.reference + 4} fill={MUTED} fontSize={12}>
          Original
        </text>
        <text x={4} y={ROWS.voice + 4} fill={MUTED} fontSize={12}>
          Vos
        </text>
        {analysis.pairs.map((pair) => {
          const referenceMs = analysis.reference_onsets_ms[pair.reference] ?? 0;
          const sungMs = analysis.sung_onsets_ms[pair.sung] ?? 0;
          return (
            <line
              key={`pair-${String(pair.reference)}`}
              x1={x(referenceMs)}
              y1={ROWS.reference}
              x2={x(sungMs)}
              y2={ROWS.voice}
              stroke={MUTED}
              strokeWidth={1.5}
              strokeDasharray={pair.credit < 1 ? "4 3" : undefined}
            >
              <title>{`Desfase ${formatOffset(pair.offset_ms)}`}</title>
            </line>
          );
        })}
        {analysis.reference_onsets_ms.map((ms, index) => (
          <circle
            key={`reference-${String(index)}`}
            cx={x(ms)}
            cy={ROWS.reference}
            r={6}
            fill={matched.has(index) ? SERIES_COLORS.reference : "none"}
            stroke={SERIES_COLORS.reference}
            strokeWidth={2}
          >
            <title>{`Golpe ${String(index + 1)}: ${String(Math.round(ms))} ms${matched.has(index) ? "" : " (te faltó)"}`}</title>
          </circle>
        ))}
        {analysis.sung_onsets_ms.map((ms, index) => (
          <circle
            key={`voice-${String(index)}`}
            cx={x(ms)}
            cy={ROWS.voice}
            r={6}
            fill={paired.has(index) ? SERIES_COLORS.voice : "none"}
            stroke={SERIES_COLORS.voice}
            strokeWidth={2}
          >
            <title>{`Tu golpe: ${String(Math.round(ms))} ms${paired.has(index) ? "" : " (de más)"}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="live-legend">
        <span
          className="chart-swatch"
          style={{ background: SERIES_COLORS.reference }}
        />
        Original
        <span className="chart-swatch" style={{ background: SERIES_COLORS.voice }} />
        Vos · círculo vacío: golpe que faltó o que sobró · línea punteada: fuera de
        tiempo
      </figcaption>
    </figure>
  );
}

/** Advice, attack chart and per-attack table of a rapped line. */
export function RhythmView({
  analysis,
  words,
}: {
  analysis: RhythmAnalysis;
  words: readonly PracticeWord[];
}) {
  return (
    <div className="practice">
      <ul className="practice-advice">
        {rhythmAdvice(analysis).map((advice) => (
          <li key={advice}>{advice}</li>
        ))}
      </ul>
      <RhythmChart analysis={analysis} words={words} />
      <details className="practice-table">
        <summary>Ver golpe por golpe</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Golpe</th>
              <th scope="col">Original</th>
              <th scope="col">Vos</th>
              <th scope="col">Desfase</th>
            </tr>
          </thead>
          <tbody>
            {attackRows(analysis).map((row) => (
              <tr key={row.index}>
                <th scope="row">{row.index + 1}</th>
                <td>{(row.referenceMs / 1000).toFixed(2).replace(".", ",")} s</td>
                <td>
                  {row.sungMs === null
                    ? "—"
                    : `${(row.sungMs / 1000).toFixed(2).replace(".", ",")} s`}
                </td>
                <td>{row.offsetMs === null ? "faltó" : formatOffset(row.offsetMs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
