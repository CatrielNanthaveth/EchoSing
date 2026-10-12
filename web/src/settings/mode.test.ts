import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadMode, modeLabel, saveMode } from "./mode";

beforeEach(() => {
  localStorage.clear();
});

describe("mode settings", () => {
  it("defaults to melody", () => {
    expect(loadMode("song-1")).toBe("melody");
  });

  it("remembers the mode per song", () => {
    saveMode("song-1", "rhythm");

    expect(loadMode("song-1")).toBe("rhythm");
    expect(loadMode("song-2")).toBe("melody");
  });

  it("ignores unknown stored values and blocked storage", () => {
    localStorage.setItem("echosing.mode.song-1", "opera");
    expect(loadMode("song-1")).toBe("melody");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => {
      saveMode("song-1", "rhythm");
    }).not.toThrow();
    expect(loadMode("song-1")).toBe("melody");
  });

  it("has Spanish labels", () => {
    expect(modeLabel("rhythm")).toBe("Rap");
  });
});
