import type {
  PitchResponse,
  SessionCreate,
  SessionCreated,
  SessionResults,
  SongDetail,
  SongPage,
} from "./types";

/** An HTTP error answered by the API. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface SongQuery {
  q?: string;
  limit?: number;
  offset?: number;
}

export type Fetch = typeof fetch;

/** Typed client of the EchoSing HTTP API. */
export class ApiClient {
  readonly baseUrl: string;
  readonly #fetch: Fetch;

  constructor(baseUrl: string, fetchImpl: Fetch = fetch.bind(globalThis)) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.#fetch = fetchImpl;
  }

  listSongs(query: SongQuery = {}, signal?: AbortSignal): Promise<SongPage> {
    const params = new URLSearchParams();
    if (query.q) params.set("q", query.q);
    if (query.limit !== undefined) params.set("limit", String(query.limit));
    if (query.offset !== undefined) params.set("offset", String(query.offset));
    const search = params.size > 0 ? `?${params.toString()}` : "";
    return this.#request(`/songs${search}`, { signal: signal ?? null });
  }

  getSong(songId: string, signal?: AbortSignal): Promise<SongDetail> {
    return this.#request(`/songs/${encodeURIComponent(songId)}`, {
      signal: signal ?? null,
    });
  }

  getPitch(songId: string, signal?: AbortSignal): Promise<PitchResponse> {
    return this.#request(`/songs/${encodeURIComponent(songId)}/pitch`, {
      signal: signal ?? null,
    });
  }

  createSession(body: SessionCreate): Promise<SessionCreated> {
    return this.#request("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  getSessionResults(sessionId: string, signal?: AbortSignal): Promise<SessionResults> {
    return this.#request(`/sessions/${encodeURIComponent(sessionId)}/results`, {
      signal: signal ?? null,
    });
  }

  /** URL of the karaoke track (MP3). */
  instrumentalUrl(songId: string): string {
    return `${this.baseUrl}/songs/${encodeURIComponent(songId)}/instrumental`;
  }

  /** WebSocket URL of a play session (same host, ws/wss scheme). */
  sessionSocketUrl(sessionId: string): string {
    const url = new URL(`${this.baseUrl}/ws/sessions/${encodeURIComponent(sessionId)}`);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }

  async #request<T>(path: string, init: RequestInit): Promise<T> {
    const response = await this.#fetch(`${this.baseUrl}${path}`, init);
    if (!response.ok) {
      throw new ApiError(response.status, await errorDetail(response));
    }
    return (await response.json()) as T;
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON: fall back to the status.
  }
  return response.statusText || `HTTP ${response.status}`;
}

export const api = new ApiClient(
  import.meta.env.VITE_API_URL ?? "http://localhost:8000",
);
