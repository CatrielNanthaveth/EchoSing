import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { App } from "./App";

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  it("shows the brand on every page", () => {
    renderAt("/");

    expect(screen.getByRole("link", { name: "EchoSing" })).toHaveAttribute("href", "/");
  });

  it("shows a not found page for unknown routes", () => {
    renderAt("/nope");

    expect(screen.getByRole("heading", { name: "Página no encontrada" })).toBeVisible();
  });
});
