import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadPlayerName, normalizePlayerName, savePlayerName } from "./player";

beforeEach(() => {
  localStorage.clear();
});

describe("player name", () => {
  it("defaults to Jugador", () => {
    expect(loadPlayerName()).toBe("Jugador");
  });

  it("saves the cleaned up name", () => {
    savePlayerName("  Ana  ");

    expect(loadPlayerName()).toBe("Ana");
  });

  it.each([
    ["", "Jugador"],
    ["   ", "Jugador"],
    ["x".repeat(60), "x".repeat(50)],
  ])("normalizes %j", (name, expected) => {
    expect(normalizePlayerName(name)).toBe(expected);
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => {
      savePlayerName("Ana");
    }).not.toThrow();
    expect(loadPlayerName()).toBe("Jugador");
  });
});
