import { useEffect, useRef, type RefObject } from "react";

import type { LyricLine, PitchResponse } from "../api/types";
import { useAnimationFrame } from "../hooks/useAnimationFrame";
import { RAW_VOICE_COLOR, SERIES_COLORS } from "../lib/chartColors";
import { midiNoteName } from "../lib/pitch";
import { COUNT_IN_MS } from "../session/practiceLoop";
import type { VoicePoint } from "../session/usePractice";
import type { ScoringMode } from "../settings/mode";

const TAIL_MS = 300;
const GRID = "#2a2f3c";
const TEXT = "#e8eaf0";
/** Reference frames below this confidence are drawn as gaps (as in scoring). */
const MIN_CONFIDENCE = 50;

interface LivePitchCanvasProps {
  line: LyricLine;
  /** Reference pitch of the line (frame 0 at the line start). */
  reference: PitchResponse;
  voice: RefObject<VoicePoint[]>;
  /** Song time being heard, or null when not playing. */
  clock: (() => number) | null;
  /** Melody draws pitch curves; rap draws loudness envelopes. */
  mode?: ScoringMode;
  height?: number;
}

/** Loudness range drawn in rap mode (dBFS). */
const LEVEL_RANGE = [-60, 0] as const;

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[sorted.length >> 1] ?? 60;
}

/**
 * The line's reference and the player's voice drawn live on a canvas
 * (redrawn every frame without re-rendering React), with a playhead and a
 * count-in before the line: pitch curves in melody mode, loudness envelopes
 * in rap mode (each syllable is a jump).
 */
export function LivePitchCanvas({
  line,
  reference,
  voice,
  clock,
  mode = "melody",
  height = 260,
}: LivePitchCanvasProps) {
  const rap = mode === "rhythm";
  const canvas = useRef<HTMLCanvasElement>(null);

  const referenceMidi = reference.midi.map((midi, i) =>
    midi !== null && (reference.confidence[i] ?? 0) >= MIN_CONFIDENCE ? midi : null,
  );
  const voiced = referenceMidi.filter((midi): midi is number => midi !== null);
  const center = median(voiced);
  const [low, high] = rap
    ? LEVEL_RANGE
    : [
        Math.floor(Math.min(...voiced, center - 3)) - 2,
        Math.ceil(Math.max(...voiced, center + 3)) + 2,
      ];
  const fromMs = line.start_ms - COUNT_IN_MS;
  const toMs = line.end_ms + TAIL_MS;

  const draw = () => {
    const element = canvas.current;
    const ctx = element?.getContext("2d");
    if (!element || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const width = element.clientWidth || 600;
    if (element.width !== Math.round(width * ratio)) {
      element.width = Math.round(width * ratio);
      element.height = Math.round(height * ratio);
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const left = 40;
    const top = 20;
    const plotWidth = width - left - 8;
    const plotHeight = height - top - 8;
    const x = (ms: number) => left + ((ms - fromMs) / (toMs - fromMs)) * plotWidth;
    const y = (value: number) =>
      top + ((high - Math.min(high, Math.max(low, value))) / (high - low)) * plotHeight;

    // Grid: note names (melody) or dB (rap).
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    const step = rap ? 12 : 2;
    for (let value = Math.ceil(low); value <= high; value++) {
      if (value % step !== 0) continue;
      ctx.strokeStyle = GRID;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(left, y(value));
      ctx.lineTo(width - 8, y(value));
      ctx.stroke();
      ctx.fillStyle = RAW_VOICE_COLOR;
      ctx.fillText(rap ? `${String(value)} dB` : midiNoteName(value), 2, y(value));
    }

    // Words above the plot.
    ctx.textBaseline = "top";
    for (const word of line.words) {
      ctx.fillStyle = RAW_VOICE_COLOR;
      ctx.fillText(word.text, x(word.start_ms) + 2, 2);
      ctx.strokeStyle = GRID;
      ctx.beginPath();
      ctx.moveTo(x(word.start_ms), top);
      ctx.lineTo(x(word.start_ms), height - 8);
      ctx.stroke();
    }

    const curve = (points: { ms: number; value: number | null }[], color: string) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.beginPath();
      let drawing = false;
      for (const point of points) {
        if (point.value === null) {
          drawing = false;
          continue;
        }
        if (drawing) ctx.lineTo(x(point.ms), y(point.value));
        else ctx.moveTo(x(point.ms), y(point.value));
        drawing = true;
      }
      ctx.stroke();
    };

    if (rap) {
      curve(
        (reference.level_db ?? []).map((db, i) => ({
          ms: reference.start_ms + i * reference.hop_ms,
          value: db,
        })),
        SERIES_COLORS.reference,
      );
      curve(
        voice.current.map((point) => ({ ms: point.songMs, value: point.db })),
        SERIES_COLORS.voice,
      );
    } else {
      curve(
        referenceMidi.map((midi, i) => ({
          ms: reference.start_ms + i * reference.hop_ms,
          value: midi,
        })),
        SERIES_COLORS.reference,
      );
      // The voice, moved by whole octaves to the melody's register.
      curve(
        voice.current.map((point) => ({
          ms: point.songMs,
          value:
            point.midi === null
              ? null
              : point.midi - 12 * Math.round((point.midi - center) / 12),
        })),
        SERIES_COLORS.voice,
      );
    }

    const now = clock?.();
    if (now !== undefined) {
      ctx.strokeStyle = TEXT;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x(now), top);
      ctx.lineTo(x(now), height - 8);
      ctx.stroke();
      if (now < line.start_ms) {
        const seconds = Math.ceil((line.start_ms - now) / 1000);
        ctx.fillStyle = TEXT;
        ctx.font = "bold 28px system-ui, sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillText(String(seconds), x(line.start_ms) + 12, top + plotHeight / 2);
      }
    }
  };

  useAnimationFrame(draw, clock !== null);
  // Draw once when idle or when the line changes (and the last attempt stays).
  useEffect(draw);

  return (
    <canvas
      ref={canvas}
      className="live-pitch"
      style={{ width: "100%", height }}
      role="img"
      aria-label={
        rap
          ? "Volumen del verso y de tu voz en vivo"
          : "Melodía del verso y tu voz en vivo"
      }
    />
  );
}
