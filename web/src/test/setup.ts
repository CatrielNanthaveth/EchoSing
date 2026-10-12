import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// The default 1 s for findBy* is too tight when the whole suite runs in
// parallel on a busy machine.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});

// jsdom has no ResizeObserver; Recharts' ResponsiveContainer needs one.
if (!("ResizeObserver" in globalThis)) {
  const noop = (): void => undefined;
  globalThis.ResizeObserver = class {
    observe = noop;
    unobserve = noop;
    disconnect = noop;
  };
}

// jsdom does not implement canvas; components skip drawing without a context.
HTMLCanvasElement.prototype.getContext = (() =>
  null) as typeof HTMLCanvasElement.prototype.getContext;
