import { useEffect, useRef } from "react";

/** Call `callback` on every animation frame while `active`. */
export function useAnimationFrame(callback: () => void, active: boolean): void {
  const latest = useRef(callback);

  useEffect(() => {
    latest.current = callback;
  });

  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const tick = () => {
      latest.current();
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [active]);
}
