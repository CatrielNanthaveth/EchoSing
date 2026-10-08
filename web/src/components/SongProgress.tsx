import { useRef } from "react";

import { useAnimationFrame } from "../hooks/useAnimationFrame";
import { formatDuration } from "../lib/format";

interface SongProgressProps {
  durationMs: number;
  /** Current song time in ms, or null when not playing. */
  clock: (() => number) | null;
}

/** Progress bar and elapsed time, updated every frame without re-rendering. */
export function SongProgress({ durationMs, clock }: SongProgressProps) {
  const bar = useRef<HTMLDivElement>(null);
  const elapsed = useRef<HTMLSpanElement>(null);

  useAnimationFrame(() => {
    if (clock === null || bar.current === null || elapsed.current === null) return;
    const timeMs = Math.min(Math.max(clock(), 0), durationMs);
    bar.current.style.width = `${(100 * timeMs) / durationMs}%`;
    elapsed.current.textContent = formatDuration(timeMs);
  }, clock !== null);

  return (
    <div className="song-progress">
      <span ref={elapsed}>0:00</span>
      <div className="song-progress-track">
        <div ref={bar} className="song-progress-bar" />
      </div>
      <span>{formatDuration(durationMs)}</span>
    </div>
  );
}
