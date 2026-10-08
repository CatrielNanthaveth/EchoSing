import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadLatency, saveLatency } from "./latency";

beforeEach(() => {
  localStorage.clear();
});

describe("latency settings", () => {
  it("is null before calibrating", () => {
    expect(loadLatency()).toBeNull();
  });

  it("saves and loads whole milliseconds", () => {
    expect(saveLatency(142.6)).toBe(true);

    expect(loadLatency()).toBe(143);
  });

  it("ignores corrupted values", () => {
    localStorage.setItem("echosing.latencyMs", "abc");

    expect(loadLatency()).toBeNull();
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(loadLatency()).toBeNull();
    expect(saveLatency(100)).toBe(false);
  });
});
