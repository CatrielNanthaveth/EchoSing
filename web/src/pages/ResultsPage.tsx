import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { LineReport, SessionResults } from "../api/types";
import { LinePracticePanel } from "../components/LinePracticePanel";
import { useAsync } from "../hooks/useAsync";
import { difficultyLabel } from "../settings/difficulty";
import { NotFoundPage } from "./NotFoundPage";

interface Loaded {
  results: SessionResults;
  title: string | null;
}

async function loadResults(sessionId: string, signal: AbortSignal): Promise<Loaded> {
  const results = await api.getSessionResults(sessionId, signal);
  // The title is a nicety: the report stands without it.
  const title = await api.getSong(results.song_id, signal).then(
    (song) => song.title,
    () => null,
  );
  return { results, title };
}

export function ResultsPage() {
  const { sessionId = "" } = useParams();
  const [state, retry] = useAsync(
    (signal) => loadResults(sessionId, signal),
    [sessionId],
  );

  if (state.status === "loading") return <p className="muted">Cargando…</p>;
  if (state.status === "error") {
    if (state.error instanceof ApiError && state.error.status === 404) {
      return <NotFoundPage />;
    }
    return (
      <div role="alert" className="error-box">
        <p>No se pudieron cargar los resultados: {state.error.message}</p>
        <button type="button" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }

  const { results, title } = state.data;
  const { totals } = results;
  return (
    <section className="results">
      <header>
        <p className="muted">
          {results.player_name} · {difficultyLabel(results.difficulty)}
          {results.status === "active" && " · sesión sin terminar"}
        </p>
        <h1>{title ?? "Resultados"}</h1>
      </header>

      <div className="results-score">
        <p className="results-score-value" aria-label="Puntaje total">
          {totals.total_score === null ? "–" : Math.round(totals.total_score)}
        </p>
        <dl className="results-stats">
          <div>
            <dt>Afinación</dt>
            <dd>
              {totals.accuracy === null ? "–" : `${Math.round(totals.accuracy * 100)}%`}
            </dd>
          </div>
          <div>
            <dt>Versos acertados</dt>
            <dd>
              {totals.hit_lines} de {totals.scored_lines}
            </dd>
          </div>
          <div>
            <dt>Mejor racha</dt>
            <dd>{totals.best_streak}</dd>
          </div>
        </dl>
      </div>

      <div className="results-actions">
        <Link to={`/songs/${results.song_id}`} className="button primary">
          Cantar de nuevo
        </Link>
        <Link to="/" className="button">
          Elegir otra canción
        </Link>
      </div>

      <h2>Verso por verso</h2>
      <ol className="results-lines">
        {results.lines.map((line) => (
          <LineRow key={line.line_index} line={line} sessionId={results.session_id} />
        ))}
      </ol>
    </section>
  );
}

function LineRow({ line, sessionId }: { line: LineReport; sessionId: string }) {
  const [open, setOpen] = useState(false);
  let label: string;
  let tone: string;
  if (line.scorable === false) {
    label = "no puntúa";
    tone = "neutral";
  } else if (!line.sung) {
    label = line.score === null ? "–" : "no cantado";
    tone = "unsung";
  } else {
    label = line.score === null ? "–" : String(Math.round(line.score));
    tone = line.hit ? "hit" : "miss";
  }
  const panelId = `practice-${String(line.line_index)}`;
  return (
    <li className={`results-line ${tone}`}>
      <div className="results-line-row">
        <span className="results-line-text">{line.text}</span>
        <span className="results-line-score">{label}</span>
        {line.sung && (
          <button
            type="button"
            className="results-line-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => {
              setOpen((value) => !value);
            }}
          >
            {open ? "Ocultar" : "Ver cómo cantaste"}
          </button>
        )}
      </div>
      {open && (
        <div id={panelId} className="results-line-practice">
          <LinePracticePanel sessionId={sessionId} lineIndex={line.line_index} />
        </div>
      )}
    </li>
  );
}
