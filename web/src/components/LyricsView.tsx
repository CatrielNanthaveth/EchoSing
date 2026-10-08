import { useState } from "react";

import type { LyricLine } from "../api/types";
import { useAnimationFrame } from "../hooks/useAnimationFrame";
import { lyricsPosition, type LyricsPosition } from "../lyrics/timeline";

/** Countdown shown before a line, in seconds. */
const COUNTDOWN_FROM_S = 3;

interface LyricsViewProps {
  lines: readonly LyricLine[];
  /** Current song time in ms, or null when not playing. */
  clock: (() => number) | null;
}

function samePosition(a: LyricsPosition, b: LyricsPosition): boolean {
  return (
    a.line === b.line &&
    a.active === b.active &&
    a.words === b.words &&
    a.countdown === b.countdown
  );
}

/**
 * Karaoke lyrics: the line to sing with its words lit as they start, and the
 * following line. Re-renders only when what is shown changes, not every frame.
 */
export function LyricsView({ lines, clock }: LyricsViewProps) {
  const [position, setPosition] = useState(() => lyricsPosition(lines, 0));

  useAnimationFrame(() => {
    if (clock === null) return;
    const next = lyricsPosition(lines, clock());
    setPosition((current) => (samePosition(current, next) ? current : next));
  }, clock !== null);

  const shown = clock === null ? lyricsPosition(lines, 0) : position;
  const line = lines[shown.line];
  const following = lines[shown.line + 1];

  if (line === undefined) {
    return (
      <div className="lyrics" aria-live="polite">
        <p className="lyrics-current muted">Fin de la letra</p>
      </div>
    );
  }

  const showCountdown =
    clock !== null &&
    !shown.active &&
    shown.countdown > 0 &&
    shown.countdown <= COUNTDOWN_FROM_S;

  return (
    <div className="lyrics">
      <p className="lyrics-countdown" aria-hidden={!showCountdown}>
        {showCountdown ? shown.countdown : " "}
      </p>
      <p
        className={`lyrics-current${shown.active ? " active" : ""}`}
        data-testid="current-line"
      >
        {line.words.map((word, index) => (
          <span
            key={`${line.index}-${index}`}
            className={index < shown.words ? "word sung" : "word"}
          >
            {word.text}{" "}
          </span>
        ))}
      </p>
      <p className="lyrics-next" data-testid="next-line">
        {following?.text ?? " "}
      </p>
    </div>
  );
}
