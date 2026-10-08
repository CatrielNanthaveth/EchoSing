import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { SongDetail } from "../api/types";
import { LyricsView } from "../components/LyricsView";
import { PitchMeter } from "../components/PitchMeter";
import { SongProgress } from "../components/SongProgress";
import { useAsync } from "../hooks/useAsync";
import type { SungLine } from "../session/lineCollector";
import { useKaraoke } from "../session/useKaraoke";
import { NotFoundPage } from "./NotFoundPage";

export function SongPage() {
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
  return <Karaoke key={state.data.id} song={state.data} />;
}

/** Share of frames with a detected pitch, 0-100. */
function voicedPercent(line: SungLine): number {
  if (line.f0Hz.length === 0) return 0;
  return Math.round((100 * line.f0Hz.filter((hz) => hz > 0).length) / line.f0Hz.length);
}

function Karaoke({ song }: { song: SongDetail }) {
  const [lastLine, setLastLine] = useState<SungLine | null>(null);
  const { phase, trackMs, microphone, play, stop } = useKaraoke(song, setLastLine);

  const clock = phase.name === "playing" ? phase.clock : null;
  const durationMs = trackMs ?? song.duration_ms ?? 0;

  return (
    <section className="karaoke">
      <header className="karaoke-header">
        <div>
          <h1>{song.title}</h1>
          <p className="muted">{song.artist}</p>
        </div>
        <Link to="/">Volver al catálogo</Link>
      </header>

      <LyricsView lines={song.lines} clock={clock} />

      {durationMs > 0 && <SongProgress durationMs={durationMs} clock={clock} />}

      <div className="karaoke-controls">
        {phase.name === "playing" ? (
          <button type="button" onClick={stop}>
            Detener
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={phase.name === "loading"}
            onClick={() => {
              setLastLine(null);
              void play();
            }}
          >
            {phase.name === "loading"
              ? "Preparando…"
              : phase.name === "ended"
                ? "Cantar de nuevo"
                : "Cantar"}
          </button>
        )}
      </div>

      {microphone !== null && <PitchMeter microphone={microphone} />}

      {lastLine !== null && (
        <p className="line-feedback" role="status">
          Verso {lastLine.lineIndex + 1}: voz detectada en {voicedPercent(lastLine)}%
        </p>
      )}

      {phase.name === "error" && (
        <p role="alert" className="error-box">
          No se pudo empezar: {phase.message}
        </p>
      )}
    </section>
  );
}
