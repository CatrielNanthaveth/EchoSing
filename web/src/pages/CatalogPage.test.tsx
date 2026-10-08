import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { songPage, songSummary } from "../test/factories";
import { CatalogPage, PAGE_SIZE } from "./CatalogPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderCatalog(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<CatalogPage />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("CatalogPage", () => {
  it("lists songs with duration, lines and a link to play them", async () => {
    vi.spyOn(api, "listSongs").mockResolvedValue(
      songPage([
        songSummary(),
        songSummary({ id: "song-2", title: "Desde la primera puerta" }),
      ]),
    );

    renderCatalog();

    const link = await screen.findByRole("link", { name: /Chachacha/ });
    expect(link).toHaveAttribute("href", "/songs/song-1");
    expect(link).toHaveTextContent("Josean Log");
    expect(link).toHaveTextContent("3:35 · 37 versos");
    expect(screen.getByRole("link", { name: /Desde la primera puerta/ })).toBeVisible();
  });

  it("marks songs being reprocessed", async () => {
    vi.spyOn(api, "listSongs").mockResolvedValue(
      songPage([songSummary({ reprocessing: true })]),
    );

    renderCatalog();

    expect(await screen.findByText("reprocesando")).toBeVisible();
  });

  it("searches after typing stops and puts the search in the URL", async () => {
    const listSongs = vi.spyOn(api, "listSongs").mockResolvedValue(songPage([]));
    const user = userEvent.setup();
    renderCatalog("/?page=3");
    await screen.findByText("Todavía no hay canciones.");

    await user.type(screen.getByRole("searchbox"), "josean");

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/?q=josean");
    });
    expect(listSongs).toHaveBeenLastCalledWith(
      { q: "josean", limit: PAGE_SIZE, offset: 0 },
      expect.any(AbortSignal),
    );
    // Debounced: one request for the initial page and one for the search.
    expect(listSongs).toHaveBeenCalledTimes(2);
    expect(
      await screen.findByText("No hay canciones que coincidan con “josean”."),
    ).toBeVisible();
  });

  it("paginates", async () => {
    const listSongs = vi
      .spyOn(api, "listSongs")
      .mockResolvedValue(songPage([songSummary()], { total: PAGE_SIZE * 2 + 1 }));
    const user = userEvent.setup();
    renderCatalog("/?q=a");

    await user.click(await screen.findByRole("button", { name: "Siguiente" }));

    expect(await screen.findByText("Página 2 de 3")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent("/?q=a&page=2");
    expect(listSongs).toHaveBeenLastCalledWith(
      { q: "a", limit: PAGE_SIZE, offset: PAGE_SIZE },
      expect.any(AbortSignal),
    );

    await user.click(screen.getByRole("button", { name: "Anterior" }));

    expect(await screen.findByText("Página 1 de 3")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent("/?q=a");
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
  });

  it("hides pagination when everything fits in one page", async () => {
    vi.spyOn(api, "listSongs").mockResolvedValue(songPage([songSummary()]));

    renderCatalog();

    await screen.findByRole("link", { name: /Chachacha/ });
    expect(screen.queryByRole("navigation", { name: "Paginación" })).toBeNull();
  });

  it("shows errors and retries", async () => {
    const listSongs = vi
      .spyOn(api, "listSongs")
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue(songPage([songSummary()]));
    const user = userEvent.setup();
    renderCatalog();

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(await screen.findByRole("link", { name: /Chachacha/ })).toBeVisible();
    expect(listSongs).toHaveBeenCalledTimes(2);
  });
});
