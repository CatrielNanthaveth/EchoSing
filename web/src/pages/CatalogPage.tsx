import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api } from "../api/client";
import type { SongSummary } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { formatDuration } from "../lib/format";

export const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

export function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [search, setSearch] = useState(query);
  const debouncedSearch = useDebouncedValue(search.trim(), SEARCH_DEBOUNCE_MS);

  // When the typed search settles, put it in the URL and go back to page 1.
  // Only reacting to new searches keeps back/forward navigation working.
  const lastSearch = useRef(debouncedSearch);
  useEffect(() => {
    if (debouncedSearch === lastSearch.current) return;
    lastSearch.current = debouncedSearch;
    const next = new URLSearchParams();
    if (debouncedSearch) next.set("q", debouncedSearch);
    setParams(next, { replace: true });
  }, [debouncedSearch, setParams]);

  const [state, retry] = useAsync(
    (signal) =>
      api.listSongs(
        { q: query, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE },
        signal,
      ),
    [query, page],
  );

  const goToPage = (target: number) => {
    const next = new URLSearchParams(params);
    if (target > 1) next.set("page", String(target));
    else next.delete("page");
    setParams(next);
  };

  return (
    <section className="catalog">
      <div className="catalog-header">
        <h1>Canciones</h1>
        <input
          type="search"
          aria-label="Buscar por título o artista"
          placeholder="Buscar por título o artista"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
      </div>

      {state.status === "loading" && <p className="muted">Cargando…</p>}

      {state.status === "error" && (
        <div role="alert" className="error-box">
          <p>No se pudo cargar el catálogo: {state.error.message}</p>
          <button type="button" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}

      {state.status === "success" && state.data.items.length === 0 && (
        <p className="empty-state muted">
          {query
            ? `No hay canciones que coincidan con “${query}”.`
            : "Todavía no hay canciones."}
        </p>
      )}

      {state.status === "success" && state.data.items.length > 0 && (
        <>
          <ul className="song-list">
            {state.data.items.map((song) => (
              <SongItem key={song.id} song={song} />
            ))}
          </ul>
          <Pagination
            page={page}
            pageCount={Math.max(1, Math.ceil(state.data.total / PAGE_SIZE))}
            onChange={goToPage}
          />
        </>
      )}
    </section>
  );
}

function SongItem({ song }: { song: SongSummary }) {
  return (
    <li>
      <Link to={`/songs/${song.id}`} className="song-card">
        <span className="song-title">{song.title}</span>
        <span className="song-artist">{song.artist}</span>
        <span className="song-meta">
          {formatDuration(song.duration_ms)} · {song.line_count} versos
          {song.reprocessing && <span className="badge">reprocesando</span>}
        </span>
      </Link>
    </li>
  );
}

interface PaginationProps {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}

function Pagination({ page, pageCount, onChange }: PaginationProps) {
  if (pageCount <= 1) return null;
  return (
    <nav className="pagination" aria-label="Paginación">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => {
          onChange(page - 1);
        }}
      >
        Anterior
      </button>
      <span>
        Página {page} de {pageCount}
      </span>
      <button
        type="button"
        disabled={page >= pageCount}
        onClick={() => {
          onChange(page + 1);
        }}
      >
        Siguiente
      </button>
    </nav>
  );
}
