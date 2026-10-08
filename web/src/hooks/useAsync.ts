import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: Error };

type Settled<T> =
  | { key: string; status: "success"; data: T }
  | { key: string; status: "error"; error: Error };

/**
 * Run an async load whenever `deps` change, aborting the previous one.
 *
 * Loading is derived: while the last settled result belongs to other deps,
 * the state is "loading" (no synchronous state reset inside the effect).
 *
 * @param load Loader; receives a signal aborted when deps change or on unmount.
 * @param deps JSON-serializable values the load depends on.
 * @returns The current state and a `retry` function.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): [AsyncState<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const key = JSON.stringify([...deps, attempt]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ key, status: "success", data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setSettled({
          key,
          status: "error",
          error: error instanceof Error ? error : new Error(String(error)),
        });
      },
    );
    return () => {
      controller.abort();
    };
    // `load` is usually an inline closure: `key` captures what it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const retry = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  if (settled?.key !== key) return [{ status: "loading" }, retry];
  return [
    settled.status === "success"
      ? { status: "success", data: settled.data }
      : { status: "error", error: settled.error },
    retry,
  ];
}
