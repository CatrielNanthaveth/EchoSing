import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { SongDetail } from "../api/types";
import { LyricsView } from "../components/LyricsView";
import { PitchMeter } from "../components/PitchMeter";
import { ScoreCard } from "../components/ScoreCard";
import { SongProgress } from "../components/SongProgress";
import { useAsync } from "../hooks/useAsync";
import { useKaraoke } from "../session/useKaraoke";
import { usePlaySession } from "../session/usePlaySession";
import {
  DIFFICULTIES,
  loadDifficulty,
  saveDifficulty,
  type Difficulty,
} from "../settings/difficulty";
import { loadLatency } from "../settings/latency";
import {
  MAX_PLAYER_NAME,
  loadPlayerName,
  normalizePlayerName,
  savePlayerName,
} from "../settings/player";
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

function Karaoke({ song }: { song: SongDetail }) {
  const [playerName, setPlayerName] = useState(loadPlayerName);
  const [difficulty, setDifficulty] = useState(loadDifficulty);
  const latencyMs = loadLatency();
  const session = usePlaySession(song);
  const karaoke = useKaraoke(song, session.sendLine, () => void session.finish());
  const { phase } = karaoke;
  const navigate = useNavigate();
  const finishedId = session.state.name === "finished" ? session.state.sessionId : null;

  useEffect(() => {
    if (finishedId !== null) void navigate(`/sessions/${finishedId}/results`);
  }, [finishedId, navigate]);

  const sing = async () => {
    const name = normalizePlayerName(playerName);
    savePlayerName(name);
    setPlayerName(name);
    if (!(await session.start(name, latencyMs ?? 0, difficulty))) return;
    if (!(await karaoke.play())) session.close();
  };

  const stop = () => {
    karaoke.stop();
    session.close();
  };

  const playing = phase.name === "playing";
  const busy = phase.name === "loading" || session.state.name === "starting";
  const clock = playing ? phase.clock : null;
  const durationMs = karaoke.trackMs ?? song.duration_ms ?? 0;
  const error =
    session.state.name === "error"
      ? session.state.message
      : phase.name === "error"
        ? `No se pudo empezar: ${phase.message}`
        : null;

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

      {!playing && (
        <div className="karaoke-setup">
          <label>
            Tu nombre{" "}
            <input
              value={playerName}
              maxLength={MAX_PLAYER_NAME}
              onChange={(event) => {
                setPlayerName(event.target.value);
              }}
            />
          </label>
          <label>
            Dificultad{" "}
            <select
              value={difficulty}
              onChange={(event) => {
                const level = event.target.value as Difficulty;
                setDifficulty(level);
                saveDifficulty(level);
              }}
            >
              {DIFFICULTIES.map((level) => (
                <option key={level.value} value={level.value}>
                  {level.label} ({level.hint})
                </option>
              ))}
            </select>
          </label>
          <p className="muted">
            {latencyMs === null ? (
              <>
                Latencia sin calibrar: <Link to="/calibrar">calibrala</Link> para un
                puntaje justo.
              </>
            ) : (
              <>
                Latencia: {latencyMs} ms (<Link to="/calibrar">recalibrar</Link>)
              </>
            )}
          </p>
        </div>
      )}

      <div className="karaoke-controls">
        {playing ? (
          <button type="button" onClick={stop}>
            Detener
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => void sing()}
          >
            {busy ? "Preparando…" : "Cantar"}
          </button>
        )}
      </div>

      {karaoke.microphone !== null && playing && (
        <PitchMeter microphone={karaoke.microphone} />
      )}

      {playing && session.lastScore !== null && (
        <ScoreCard key={session.lastScore.line_index} score={session.lastScore} />
      )}

      {playing && session.connection === "reconnecting" && (
        <p className="muted connection">Reconectando con el servidor…</p>
      )}
      {session.connection === "failed" && session.state.name !== "error" && (
        <p role="alert" className="error-box">
          Se perdió la conexión: los versos siguientes no se van a puntuar.
        </p>
      )}

      {session.state.name === "finishing" && (
        <p className="muted" role="status">
          Calculando el resultado…
        </p>
      )}

      {error !== null && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
    </section>
  );
}
