import { useState } from "react";

import { api } from "../api/client";
import type { LineAnalysis, LinePractice, PracticeWord } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { midiNoteName } from "../lib/pitch";
import { chartRows, practiceAdvice, wordStats } from "../lib/practice";
import { PitchChart } from "./PitchChart";

const NOT_SUNG = "No cantaste este verso.";
const NOT_STORED =
  "Este verso se cantó antes de que guardáramos las curvas: no hay gráfico.";

function formatOffset(offset: number | null): string {
  if (offset === null) return "—";
  const rounded = Math.round(offset * 10) / 10;
  if (rounded === 0) return "0";
  return `${rounded > 0 ? "+" : "−"}${String(Math.abs(rounded)).replace(".", ",")}`;
}

/** How the player sang one line: advice, chart and per-word table. */
export function LinePracticePanel({
  sessionId,
  lineIndex,
}: {
  sessionId: string;
  lineIndex: number;
}) {
  const [state, retry] = useAsync(
    (signal) => api.getLineAnalysis(sessionId, lineIndex, signal),
    [sessionId, lineIndex],
  );

  if (state.status === "loading") return <p className="muted">Analizando…</p>;
  if (state.status === "error") {
    return (
      <div role="alert" className="error-box">
        <p>No se pudo analizar el verso: {state.error.message}</p>
        <button type="button" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }
  return <PracticeView practice={state.data} />;
}

export function PracticeView({ practice }: { practice: LinePractice }) {
  const { analysis } = practice;
  if (analysis === null) {
    return (
      <p className="muted">
        {practice.status === "not_stored" ? NOT_STORED : NOT_SUNG}
      </p>
    );
  }

  return <AnalysisView analysis={analysis} words={practice.words} />;
}

/** Advice, chart and per-word table of an analyzed line (session or practice). */
export function AnalysisView({
  analysis,
  words,
}: {
  analysis: LineAnalysis;
  words: readonly PracticeWord[];
}) {
  const [aligned, setAligned] = useState(false);
  const stats = wordStats(words, analysis);
  return (
    <div className="practice">
      <ul className="practice-advice">
        {practiceAdvice(analysis).map((advice) => (
          <li key={advice}>{advice}</li>
        ))}
      </ul>
      <label className="practice-toggle">
        <input
          type="checkbox"
          checked={aligned}
          onChange={(event) => {
            setAligned(event.target.checked);
          }}
        />{" "}
        Corregir el ritmo (ver solo la afinación)
      </label>
      <PitchChart rows={chartRows(analysis, aligned)} words={words} />
      <details className="practice-table">
        <summary>Ver por palabra</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Palabra</th>
              <th scope="col">Melodía</th>
              <th scope="col">Tu voz</th>
              <th scope="col">Diferencia (semitonos)</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((word, index) => (
              <tr key={`${word.text}-${String(index)}`}>
                <th scope="row">{word.text}</th>
                <td>{word.reference === null ? "—" : midiNoteName(word.reference)}</td>
                <td>{word.voice === null ? "—" : midiNoteName(word.voice)}</td>
                <td>{formatOffset(word.offset)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
