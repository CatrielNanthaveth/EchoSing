import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { LineScoreMessage, SessionSummaryMessage, SongDetail } from "../api/types";
import type { Difficulty } from "../settings/difficulty";
import type { SungLine } from "./lineCollector";
import { SessionSocket, type SocketStatus } from "./sessionSocket";

export type SessionState =
  | { name: "none" }
  | { name: "starting" }
  | { name: "live"; sessionId: string }
  | { name: "finishing"; sessionId: string }
  | { name: "finished"; sessionId: string; summary: SessionSummaryMessage }
  | { name: "error"; message: string };

export interface PlaySession {
  state: SessionState;
  /** Latest scored line, for the live feedback. */
  lastScore: LineScoreMessage | null;
  connection: SocketStatus | null;
  /** Start a session; resolves to false if it could not be created. */
  start: (
    playerName: string,
    latencyMs: number,
    difficulty: Difficulty,
  ) => Promise<boolean>;
  sendLine: (line: SungLine) => void;
  finish: () => Promise<void>;
  /** Abandon the session (the player stopped the song). */
  close: () => void;
}

/** A play session scored in real time over the WebSocket. */
export function usePlaySession(song: SongDetail): PlaySession {
  const [state, setState] = useState<SessionState>({ name: "none" });
  const [lastScore, setLastScore] = useState<LineScoreMessage | null>(null);
  const [connection, setConnection] = useState<SocketStatus | null>(null);
  const socket = useRef<SessionSocket | null>(null);

  useEffect(
    () => () => {
      socket.current?.close();
    },
    [],
  );

  const close = useCallback(() => {
    socket.current?.close();
    socket.current = null;
    setState({ name: "none" });
  }, []);

  const start = useCallback(
    async (playerName: string, latencyMs: number, difficulty: Difficulty) => {
      socket.current?.close();
      socket.current = null;
      setLastScore(null);
      setState({ name: "starting" });
      try {
        const created = await api.createSession({
          song_id: song.id,
          player_name: playerName,
          latency_offset_ms: latencyMs,
          difficulty,
        });
        if (created.analysis_id !== song.analysis_id) {
          setState({
            name: "error",
            message: "La canción se actualizó mientras la mirabas. Recargá la página.",
          });
          return false;
        }
        socket.current = new SessionSocket(api.sessionSocketUrl(created.session_id), {
          onScore: setLastScore,
          onStatus: setConnection,
        });
        setState({ name: "live", sessionId: created.session_id });
        return true;
      } catch (error) {
        setState({
          name: "error",
          message: `No se pudo crear la sesión: ${error instanceof Error ? error.message : String(error)}`,
        });
        return false;
      }
    },
    [song.id, song.analysis_id],
  );

  const sendLine = useCallback((line: SungLine) => {
    socket.current?.sendLine({
      line_index: line.lineIndex,
      hop_ms: line.hopMs,
      f0_hz: line.f0Hz,
    });
  }, []);

  const finish = useCallback(async () => {
    const current = socket.current;
    if (current === null) return;
    setState((previous) =>
      previous.name === "live"
        ? { name: "finishing", sessionId: previous.sessionId }
        : previous,
    );
    try {
      const summary = await current.finish();
      setState((previous) =>
        previous.name === "finishing"
          ? { name: "finished", sessionId: previous.sessionId, summary }
          : previous,
      );
    } catch (error) {
      setState({
        name: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      if (socket.current === current) socket.current = null;
    }
  }, []);

  return { state, lastScore, connection, start, sendLine, finish, close };
}
