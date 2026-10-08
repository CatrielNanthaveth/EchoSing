import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { LineAnalysis, LyricLine, PitchResponse, SongDetail } from "../api/types";
import { getAudioContext, loadTrack, outputLatencyMs } from "../audio/context";
import { HOP_SIZE } from "../audio/frameAnalyzer";
import { playGuide } from "../audio/guideTone";
import { Microphone, microphoneErrorMessage } from "../audio/microphone";
import { Playback } from "../audio/playback";
import { hzToMidi } from "../lib/pitch";
import type { Difficulty } from "../settings/difficulty";
import { PracticeLoop, type LoopPhase } from "./practiceLoop";

export type PracticePhase = LoopPhase | { name: "loading" };

/** A point of the live voice curve, on the song timeline as heard. */
export interface VoicePoint {
  songMs: number;
  /** MIDI, null where there was no voice. */
  midi: number | null;
}

export interface Practice {
  phase: PracticePhase;
  /** Scores of the attempts at the current line, in order. */
  history: (number | null)[];
  /** Analysis of the last attempt (kept while singing the next one). */
  last: LineAnalysis | null;
  /** Live voice of the current attempt (mutated in place: read it per frame). */
  voice: React.RefObject<VoicePoint[]>;
  /** Song time being heard (ms), or null when not playing. */
  clock: (() => number) | null;
  /** Start looping a line; its reference pitch is needed for the guide. */
  start: (line: LyricLine, reference: PitchResponse | null) => Promise<void>;
  /** Whether a guide melody plays with each attempt (from the next one). */
  guide: boolean;
  setGuide: (on: boolean) => void;
  /** Stop looping; the last result stays visible. */
  stop: () => void;
  /** Stop and forget the attempts (e.g. another line was chosen). */
  clear: () => void;
}

/**
 * Live practice of one line at a time: plays it in a loop, draws the voice
 * as it is sung and scores every attempt (nothing is stored).
 */
export function usePractice(
  song: SongDetail,
  latencyMs: number,
  difficulty: Difficulty,
): Practice {
  const [phase, setPhase] = useState<PracticePhase>({ name: "idle" });
  const [history, setHistory] = useState<(number | null)[]>([]);
  const [last, setLast] = useState<LineAnalysis | null>(null);
  const [clock, setClock] = useState<(() => number) | null>(null);
  const [guide, setGuide] = useState(false);
  const guideReference = useRef<{ on: boolean; pitch: PitchResponse | null }>({
    on: false,
    pitch: null,
  });
  const voice = useRef<VoicePoint[]>([]);
  const loop = useRef<PracticeLoop | null>(null);
  const mic = useRef<Microphone | null>(null);
  const settings = useRef({ latencyMs, difficulty });

  useEffect(() => {
    settings.current = { latencyMs, difficulty };
    guideReference.current.on = guide;
  });

  useEffect(
    () => () => {
      loop.current?.stop();
      mic.current?.close();
    },
    [],
  );

  const ensureLoop = useCallback(async (): Promise<PracticeLoop> => {
    if (loop.current !== null) return loop.current;
    const context = getAudioContext();
    await context.resume();
    mic.current ??= await Microphone.open(context);
    const playback = new Playback(
      context,
      await loadTrack(context, api.instrumentalUrl(song.id)),
    );
    const heardLatency = outputLatencyMs(context);
    setClock(() => () => playback.positionMs() - heardLatency);
    loop.current = new PracticeLoop({
      playback,
      microphone: mic.current,
      hopMs: (HOP_SIZE / context.sampleRate) * 1000,
      score: (sung) =>
        api.scoreAttempt(song.id, sung.lineIndex, {
          analysis_id: song.analysis_id,
          hop_ms: sung.hopMs,
          f0_hz: sung.f0Hz,
          latency_offset_ms: settings.current.latencyMs,
          difficulty: settings.current.difficulty,
        }),
      onPhase: (next) => {
        if (next.name === "playing") voice.current = [];
        if (next.name === "result") {
          setHistory((scores) => [...scores, next.analysis.result.score]);
          setLast(next.analysis);
        }
        setPhase(next);
      },
      onAttemptStart: (lineStartAt) => {
        const { on, pitch } = guideReference.current;
        return on && pitch !== null
          ? playGuide(context, pitch, lineStartAt)
          : undefined;
      },
      onVoice: (songMs, f0) => {
        // Show the voice where it was sung, not where it arrived.
        voice.current.push({
          songMs: songMs - settings.current.latencyMs,
          midi: f0 > 0 ? hzToMidi(f0) : null,
        });
      },
    });
    return loop.current;
  }, [song.id, song.analysis_id]);

  const start = useCallback(
    async (line: LyricLine, reference: PitchResponse | null) => {
      guideReference.current.pitch = reference;
      setHistory([]);
      setLast(null);
      setPhase({ name: "loading" });
      try {
        (await ensureLoop()).start(line);
      } catch (error) {
        setPhase({ name: "error", message: microphoneErrorMessage(error) });
      }
    },
    [ensureLoop],
  );

  const stop = useCallback(() => {
    loop.current?.stop();
  }, []);

  const clear = useCallback(() => {
    loop.current?.stop();
    voice.current = [];
    setHistory([]);
    setLast(null);
  }, []);

  const playing = phase.name === "playing";
  return {
    phase,
    history,
    last,
    voice,
    clock: playing ? clock : null,
    start,
    stop,
    clear,
    guide,
    setGuide,
  };
}
