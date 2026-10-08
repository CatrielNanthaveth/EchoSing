import { beforeEach, describe, expect, it, vi } from "vitest";

import { difficultyLabel, loadDifficulty, saveDifficulty } from "./difficulty";

beforeEach(() => {
  localStorage.clear();
});

describe("difficulty settings", () => {
  it("defaults to normal", () => {
    expect(loadDifficulty()).toBe("normal");
  });

  it("remembers the chosen level", () => {
    saveDifficulty("easy");

    expect(loadDifficulty()).toBe("easy");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("echosing.difficulty", "extreme");

    expect(loadDifficulty()).toBe("normal");
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => {
      saveDifficulty("hard");
    }).not.toThrow();
    expect(loadDifficulty()).toBe("normal");
  });

  it("has Spanish labels", () => {
    expect(difficultyLabel("easy")).toBe("Fácil");
    expect(difficultyLabel("hard")).toBe("Difícil");
  });
});
