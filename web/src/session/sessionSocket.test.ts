import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FakeSocket,
  SUMMARY_MESSAGE,
  lastSocket,
  lineScoreMessage,
  readyMessage,
} from "../test/fakeSocket";
import {
  SessionSocket,
  type SessionSocketEvents,
  type SocketStatus,
} from "./sessionSocket";

function line(index: number) {
  return { line_index: index, hop_ms: 10.667, f0_hz: [0, 220] };
}

function open(events: SessionSocketEvents = {}) {
  const sockets: FakeSocket[] = [];
  const statuses: SocketStatus[] = [];
  const session = new SessionSocket(
    "ws://api.test/ws/sessions/s",
    {
      ...events,
      onStatus: (status) => statuses.push(status),
    },
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket as unknown as WebSocket;
    },
  );
  const current = () => lastSocket(sockets);
  return { session, sockets, statuses, current };
}

function sentIndexes(socket: FakeSocket) {
  return socket.sent.map((message) =>
    message.type === "line_pitch" ? message.line_index : message.type,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SessionSocket", () => {
  it("queues lines until the server is ready, then reports scores", () => {
    const onScore = vi.fn();
    const { session, current, statuses } = open({ onScore });

    session.sendLine(line(0));
    expect(current().sent).toEqual([]);

    current().receive(readyMessage());
    session.sendLine(line(1));
    expect(current().sent).toEqual([
      { type: "line_pitch", ...line(0) },
      { type: "line_pitch", ...line(1) },
    ]);

    current().receive(lineScoreMessage(0));
    expect(onScore).toHaveBeenCalledWith(expect.objectContaining({ line_index: 0 }));
    expect(statuses).toEqual(["connecting", "open"]);
  });

  it("reconnects and resends only the lines not scored yet", () => {
    const { session, sockets, current, statuses } = open();
    current().receive(readyMessage());
    session.sendLine(line(0));
    session.sendLine(line(1));
    session.sendLine(line(2));
    current().receive(lineScoreMessage(0));

    current().drop();
    expect(statuses.at(-1)).toBe("reconnecting");
    vi.advanceTimersByTime(250);
    expect(sockets).toHaveLength(2);

    // Line 1 was scored before the drop, but its reply was lost.
    current().receive(readyMessage([0, 1]));
    expect(sentIndexes(current())).toEqual([2]);
    expect(statuses.at(-1)).toBe("open");
  });

  it("treats line_already_scored as scored", () => {
    const onError = vi.fn();
    const { session, current } = open({ onError });
    current().receive(readyMessage());
    session.sendLine(line(4));

    current().receive({
      type: "error",
      code: "line_already_scored",
      detail: "Line 4 was already scored",
    });
    current().drop();
    vi.advanceTimersByTime(250);
    current().receive(readyMessage());

    expect(current().sent).toEqual([]);
    expect(onError).toHaveBeenCalledOnce();
  });

  it("finishes after the pending lines and resolves with the summary", async () => {
    const { session, current, statuses } = open();
    current().receive(readyMessage());
    session.sendLine(line(0));

    const summary = session.finish();
    current().receive(lineScoreMessage(0));
    current().receive(SUMMARY_MESSAGE);

    await expect(summary).resolves.toEqual(SUMMARY_MESSAGE);
    expect(sentIndexes(current())).toEqual([0, "finish"]);
    expect(current().close).toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("closed");
  });

  it("finishes after reconnecting if the connection dropped", async () => {
    const { session, current } = open();
    session.sendLine(line(0));
    const summary = session.finish();

    current().drop();
    vi.advanceTimersByTime(250);
    current().receive(readyMessage());
    expect(sentIndexes(current())).toEqual([0, "finish"]);
    current().receive(SUMMARY_MESSAGE);

    await expect(summary).resolves.toMatchObject({ total_score: 88.4 });
  });

  it.each([4404, 4409])("gives up on close code %d", async (code) => {
    const { session, sockets, current, statuses } = open();
    const summary = session.finish();

    current().drop(code);
    vi.advanceTimersByTime(10_000);

    expect(sockets).toHaveLength(1);
    expect(statuses.at(-1)).toBe("failed");
    await expect(summary).rejects.toThrow("Se perdió la conexión");
  });

  it("gives up after several failed reconnections", () => {
    const { sockets, current, statuses } = open();

    for (let i = 0; i < 6; i++) {
      current().drop();
      vi.advanceTimersByTime(5000);
    }

    expect(sockets).toHaveLength(6);
    expect(statuses.at(-1)).toBe("failed");
  });

  it("closes without finishing", async () => {
    const { session, sockets, current, statuses } = open();
    current().receive(readyMessage());
    const summary = session.finish();

    session.close();
    current().drop();
    vi.advanceTimersByTime(10_000);

    await expect(summary).rejects.toThrow("se cerró");
    await expect(session.finish()).rejects.toThrow("ya está cerrada");
    expect(sockets).toHaveLength(1);
    expect(statuses.at(-1)).toBe("closed");
  });
});
