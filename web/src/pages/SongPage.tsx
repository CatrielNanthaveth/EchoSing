import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { SongDetail } from "../api/types";
import { getAudioContext, loadTrack, outputLatencyMs } from "../audio/context";
import { Playback } from "../audio/playback";
import { LyricsView } from "../components/LyricsView";
import { SongProgress } from "../components/SongProgress";
import { useAsync } from "../hooks/useAsync";
import { NotFoundPage } from "./NotFoundPage";

type Phase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "playing"; clock: () => number }
  | { name: "ended" }
  | { name: "error"; message: string };

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
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [trackMs, setTrackMs] = useState<number | null>(null);
  const playback = useRef<Playback | null>(null);
  const loading = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      loading.current?.abort();
      playback.current?.stop();
    },
    [],
  );

  const play = useCallback(async () => {
    const context = getAudioContext();
    try {
      await context.resume();
      if (playback.current === null) {
        setPhase({ name: "loading" });
        loading.current = new AbortController();
        const buffer = await loadTrack(
          context,
          api.instrumentalUrl(song.id),
          loading.current.signal,
        );
        playback.current = new Playback(context, buffer);
        setTrackMs(playback.current.durationMs);
      }
      const player = playback.current;
      player.start(() => {
        setPhase({ name: "ended" });
      });
      // Lyrics follow what is heard, not what is scheduled.
      const latencyMs = outputLatencyMs(context);
      setPhase({ name: "playing", clock: () => player.positionMs() - latencyMs });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setPhase({
        name: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }, [song.id]);

  const stop = () => {
    playback.current?.stop();
    setPhase({ name: "idle" });
  };

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
            onClick={() => void play()}
          >
            {phase.name === "loading"
              ? "Descargando pista…"
              : phase.name === "ended"
                ? "Cantar de nuevo"
                : "Reproducir"}
          </button>
        )}
      </div>

      {phase.name === "error" && (
        <p role="alert" className="error-box">
          No se pudo reproducir: {phase.message}
        </p>
      )}
    </section>
  );
}
