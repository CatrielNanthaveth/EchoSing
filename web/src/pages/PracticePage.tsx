import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { LyricLine, SongDetail } from "../api/types";
import { AnalysisView } from "../components/LinePracticePanel";
import { LivePitchCanvas } from "../components/LivePitchCanvas";
import { useAsync } from "../hooks/useAsync";
import { SERIES_COLORS } from "../lib/chartColors";
import { usePractice } from "../session/usePractice";
import { difficultyLabel, loadDifficulty } from "../settings/difficulty";
import { loadLatency } from "../settings/latency";
import { NotFoundPage } from "./NotFoundPage";

export function PracticePage() {
  const { songId = "" } = useParams();
  const [state, retry] = useAsync((signal) => api.getSong(songId, signal), [songId]);

  if (state.status === "loading") return <p className="muted">Cargando…</p>;
  if (state.status === "error") {
    if (state.error instanceof ApiError && state.error.status === 404) {
      return <NotFoundPage />;
    }
    return (
      <div role="alert" className="error-box">
        <p>No se pudo cargar la canción: {state.error.message}</p>
        <button type="button" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }
  return <Practice key={state.data.id} song={state.data} />;
}

function Practice({ song }: { song: SongDetail }) {
  const [params, setParams] = useSearchParams();
  const requested = Number(params.get("verso")) - 1;
  const lineIndex =
    Number.isInteger(requested) && song.lines[requested] !== undefined ? requested : 0;
  const line = song.lines[lineIndex];
  const latencyMs = loadLatency() ?? 0;
  const difficulty = loadDifficulty();
  const practice = usePractice(song, latencyMs, difficulty);

  const select = (index: number) => {
    practice.clear();
    setParams({ verso: String(index + 1) }, { replace: true });
  };

  return (
    <section className="practice-page">
      <header className="karaoke-header">
        <div>
          <p className="muted">Práctica · {difficultyLabel(difficulty)}</p>
          <h1>{song.title}</h1>
          <p className="muted">{song.artist}</p>
        </div>
        <Link to={`/songs/${song.id}`}>Cantar la canción</Link>
      </header>

      <div className="admin-layout">
        <nav className="admin-lines" aria-label="Versos">
          <ol>
            {song.lines.map((item) => (
              <li key={item.index}>
                <button
                  type="button"
                  aria-current={item.index === lineIndex ? "true" : undefined}
                  onClick={() => {
                    select(item.index);
                  }}
                >
                  <span>{item.index + 1}.</span> {item.text}
                </button>
              </li>
            ))}
          </ol>
        </nav>
        {line !== undefined && (
          <LinePractice key={line.index} song={song} line={line} practice={practice} />
        )}
      </div>
    </section>
  );
}

function LinePractice({
  song,
  line,
  practice,
}: {
  song: SongDetail;
  line: LyricLine;
  practice: ReturnType<typeof usePractice>;
}) {
  const [reference, retry] = useAsync(
    (signal) => api.getPitch(song.id, signal, line.index),
    [song.id, line.index],
  );
  const { phase, history, last } = practice;
  const running =
    phase.name === "playing" || phase.name === "scoring" || phase.name === "result";

  return (
    <article className="practice-line">
      <h2 className="practice-line-text">{line.text}</h2>

      {reference.status === "loading" && <p className="muted">Cargando la melodía…</p>}
      {reference.status === "error" && (
        <div role="alert" className="error-box">
          <p>No se pudo cargar la melodía: {reference.error.message}</p>
          <button type="button" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}
      {reference.status === "success" && (
        <>
          <LivePitchCanvas
            line={line}
            reference={reference.data}
            voice={practice.voice}
            clock={practice.clock}
          />
          <p className="live-legend" aria-hidden="true">
            <span
              className="chart-swatch"
              style={{ background: SERIES_COLORS.reference }}
            />
            Melodía
            <span
              className="chart-swatch"
              style={{ background: SERIES_COLORS.voice }}
            />
            Tu voz
          </p>
        </>
      )}

      <div className="karaoke-controls">
        {running ? (
          <button type="button" onClick={practice.stop}>
            Detener
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={phase.name === "loading" || reference.status !== "success"}
            onClick={() => void practice.start(line)}
          >
            {phase.name === "loading" ? "Preparando…" : "Practicar este verso"}
          </button>
        )}
      </div>

      <p className="practice-status muted" role="status">
        {phase.name === "playing" &&
          "Escuchá la entrada y cantá cuando empiece el verso."}
        {phase.name === "scoring" && "Calculando…"}
        {phase.name === "result" && "Otra vez en un momento…"}
      </p>

      {phase.name === "error" && (
        <p role="alert" className="error-box">
          No se pudo practicar: {phase.message}
        </p>
      )}

      {history.length > 0 && (
        <p className="practice-history" aria-label="Intentos">
          Intentos:{" "}
          {history.map((score, index) => (
            <span key={index} className="practice-attempt">
              {score === null ? "—" : Math.round(score)}
            </span>
          ))}
        </p>
      )}

      {last !== null && (
        <AnalysisView
          analysis={last}
          words={line.words.map((word) => ({
            text: word.text,
            start_ms: word.start_ms - line.start_ms,
            end_ms: word.end_ms - line.start_ms,
          }))}
        />
      )}
    </article>
  );
}
