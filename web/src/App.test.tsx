import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { api } from "./api/client";
import { songPage } from "./test/factories";

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  it("opens on the catalog, with the brand on every page", async () => {
    vi.spyOn(api, "listSongs").mockResolvedValue(songPage([]));

    renderAt("/");

    expect(screen.getByRole("link", { name: "EchoSing" })).toHaveAttribute("href", "/");
    expect(await screen.findByRole("heading", { name: "Canciones" })).toBeVisible();
  });

  it("shows a not found page for unknown routes", () => {
    renderAt("/nope");

    expect(screen.getByRole("heading", { name: "Página no encontrada" })).toBeVisible();
  });
});
