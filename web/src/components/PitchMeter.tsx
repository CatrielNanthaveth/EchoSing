import { useEffect, useRef } from "react";

import type { Microphone } from "../audio/microphone";
import { levelFraction, noteName } from "../lib/pitch";

/**
 * Live microphone level and detected note. Frames arrive ~90 times per
 * second, so the DOM is updated directly instead of re-rendering.
 */
export function PitchMeter({ microphone }: { microphone: Microphone }) {
  const level = useRef<HTMLDivElement>(null);
  const note = useRef<HTMLSpanElement>(null);

  useEffect(
    () =>
      microphone.subscribe((frame) => {
        if (level.current !== null) {
          level.current.style.width = `${100 * levelFraction(frame.rms)}%`;
        }
        if (note.current !== null) {
          note.current.textContent = noteName(frame.f0) ?? "–";
        }
      }),
    [microphone],
  );

  return (
    <div className="pitch-meter" aria-label="Micrófono">
      <span className="pitch-meter-note" ref={note}>
        –
      </span>
      <div className="pitch-meter-track">
        <div className="pitch-meter-level" ref={level} />
      </div>
    </div>
  );
}
