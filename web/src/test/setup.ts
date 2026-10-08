import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

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
