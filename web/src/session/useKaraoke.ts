import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { SongDetail } from "../api/types";
import { getAudioContext, loadTrack, outputLatencyMs } from "../audio/context";
import { HOP_SIZE } from "../audio/frameAnalyzer";
import { Microphone, microphoneErrorMessage } from "../audio/microphone";
import { Playback } from "../audio/playback";
import { LineCollector, type SungLine } from "./lineCollector";

export type KaraokePhase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "playing"; clock: () => number }
  | { name: "ended" }
  | { name: "error"; message: string };

export interface Karaoke {
  phase: KaraokePhase;
  /** Duration of the track once downloaded. */
  trackMs: number | null;
  /** Open microphone (after the first play). */
  microphone: Microphone | null;
  play: () => Promise<void>;
  stop: () => void;
}

/**
 * Plays a song while capturing the singer's pitch line by line.
 *
 * Playback and microphone share one AudioContext clock: each microphone frame
 * is placed on the song timeline exactly, then grouped by lyric line.
 *
 * @param onLine Called with the pitch sung over each line, after its tail.
 * @param onEnd Called when the track finishes on its own (after the last line).
 */
export function useKaraoke(
  song: SongDetail,
  onLine: (line: SungLine) => void,
  onEnd?: () => void,
): Karaoke {
  const [phase, setPhase] = useState<KaraokePhase>({ name: "idle" });
  const [trackMs, setTrackMs] = useState<number | null>(null);
  const [microphone, setMicrophone] = useState<Microphone | null>(null);
  const playback = useRef<Playback | null>(null);
  const mic = useRef<Microphone | null>(null);
  const capture = useRef<(() => void) | null>(null);
  const loading = useRef<AbortController | null>(null);
  const callbacks = useRef({ onLine, onEnd });

  useEffect(() => {
    callbacks.current = { onLine, onEnd };
  });

  const stopCapture = () => {
    capture.current?.();
    capture.current = null;
  };

  useEffect(
    () => () => {
      loading.current?.abort();
      capture.current?.();
      playback.current?.stop();
      mic.current?.close();
    },
    [],
  );

  const play = useCallback(async () => {
    const context = getAudioContext();
    try {
      setPhase({ name: "loading" });
      await context.resume();
      if (mic.current === null) {
        mic.current = await Microphone.open(context);
        setMicrophone(mic.current);
      }
      if (playback.current === null) {
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
      const microphone = mic.current;

      stopCapture();
      const collector = new LineCollector(
        song.lines,
        (HOP_SIZE / context.sampleRate) * 1000,
        (line) => {
          callbacks.current.onLine(line);
        },
      );
      const unsubscribe = microphone.subscribe((frame) => {
        const songMs = player.songTimeAt(frame.time);
        if (songMs >= 0) collector.add(songMs, frame.f0);
      });
      capture.current = unsubscribe;

      player.start(() => {
        collector.flush();
        stopCapture();
        setPhase({ name: "ended" });
        callbacks.current.onEnd?.();
      });
      // Lyrics follow what is heard, not what is scheduled.
      const latencyMs = outputLatencyMs(context);
      setPhase({ name: "playing", clock: () => player.positionMs() - latencyMs });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setPhase({ name: "error", message: microphoneErrorMessage(error) });
    }
  }, [song.id, song.lines]);

  const stop = useCallback(() => {
    stopCapture();
    playback.current?.stop();
    setPhase({ name: "idle" });
  }, []);

  return { phase, trackMs, microphone, play, stop };
}
