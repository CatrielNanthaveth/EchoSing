import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientReturning(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  return { client: new ApiClient("http://api.test/", fetchMock), fetchMock };
}

function requestedUrls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>): unknown[] {
  return fetchMock.mock.calls.map(([url]) => url);
}

describe("ApiClient", () => {
  it("lists songs with the given query", async () => {
    const page = { items: [], total: 0, limit: 20, offset: 40 };
    const { client, fetchMock } = clientReturning(jsonResponse(page));

    await expect(
      client.listSongs({ q: "cha cha", limit: 20, offset: 40 }),
    ).resolves.toEqual(page);

    expect(requestedUrls(fetchMock)).toEqual([
      "http://api.test/songs?q=cha+cha&limit=20&offset=40",
    ]);
  });

  it("omits empty queries", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse({ items: [] }));

    await client.listSongs({ q: "" });

    expect(requestedUrls(fetchMock)).toEqual(["http://api.test/songs"]);
  });

  it("gets a song, its pitch and session results", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(jsonResponse({})));
    const client = new ApiClient("http://api.test", fetchMock);

    await client.getSong("a b");
    await client.getPitch("s1");
    await client.getSessionResults("x1");
    await client.getLineAnalysis("x1", 3);

    expect(requestedUrls(fetchMock)).toEqual([
      "http://api.test/songs/a%20b",
      "http://api.test/songs/s1/pitch",
      "http://api.test/sessions/x1/results",
      "http://api.test/sessions/x1/lines/3/analysis",
    ]);
  });

  it("creates a session with a JSON body", async () => {
    const { client, fetchMock } = clientReturning(
      jsonResponse({ session_id: "s" }, 201),
    );
    const body = {
      song_id: "song",
      player_name: "Ana",
      latency_offset_ms: 120,
      difficulty: "easy" as const,
    };

    await client.createSession(body);

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(typeof init?.body).toBe("string");
    expect(JSON.parse(init?.body as string)).toEqual(body);
  });

  it("raises ApiError with the API detail", async () => {
    const { client } = clientReturning(
      jsonResponse({ detail: "Song x is not available" }, 404),
    );

    const error: unknown = await client.getSong("x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, message: "Song x is not available" });
  });

  it("falls back to the status when the error is not JSON", async () => {
    const { client } = clientReturning(new Response("boom", { status: 502 }));

    await expect(client.getSong("x")).rejects.toMatchObject({
      status: 502,
      message: "HTTP 502",
    });
  });

  it("posts practice attempts", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse({}));
    const attempt = {
      analysis_id: "a1",
      hop_ms: 10,
      f0_hz: [0, 220],
      latency_offset_ms: 50,
      difficulty: "easy" as const,
    };

    await client.scoreAttempt("s1", 4, attempt);

    expect(requestedUrls(fetchMock)).toEqual([
      "http://api.test/songs/s1/lines/4/attempt",
    ]);
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(attempt);
  });

  it("sends the admin token for diagnostics", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse({}));

    await client.getLineDiagnostics("x1", 2, "secret");

    expect(requestedUrls(fetchMock)).toEqual([
      "http://api.test/admin/sessions/x1/lines/2/debug",
    ]);
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({
      "X-Admin-Token": "secret",
    });
  });

  it("builds media and WebSocket URLs", () => {
    expect(new ApiClient("http://api.test").instrumentalUrl("s1")).toBe(
      "http://api.test/songs/s1/instrumental",
    );
    expect(new ApiClient("http://api.test").sessionSocketUrl("x")).toBe(
      "ws://api.test/ws/sessions/x",
    );
    expect(new ApiClient("https://api.test").sessionSocketUrl("x")).toBe(
      "wss://api.test/ws/sessions/x",
    );
  });
});
