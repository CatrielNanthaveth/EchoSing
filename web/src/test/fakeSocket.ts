import { vi } from "vitest";

import type { ClientMessage, ServerMessage } from "../api/types";

/** In-memory WebSocket: records what is sent and lets tests play the server. */
export class FakeSocket {
  static readonly instances: FakeSocket[] = [];
  readyState: number = WebSocket.CONNECTING;
  sent: ClientMessage[] = [];
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = WebSocket.CLOSED;
  });
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data) as ClientMessage);
  }

  receive(message: ServerMessage): void {
    this.readyState = WebSocket.OPEN;
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent<string>);
  }

  drop(code = 1006): void {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code } as CloseEvent);
  }
}

export function readyMessage(scored: number[] = []): ServerMessage {
  return {
    type: "ready",
    session_id: "session-1",
    analysis_id: "analysis-1",
    line_count: 3,
    scored_lines: scored,
  };
}

export function lineScoreMessage(
  index: number,
  overrides: Partial<Extract<ServerMessage, { type: "line_score" }>> = {},
): ServerMessage {
  return {
    type: "line_score",
    line_index: index,
    scorable: true,
    score: 90,
    accuracy: 0.8,
    hit: true,
    streak: index + 1,
    ...overrides,
  };
}

export const SUMMARY_MESSAGE: ServerMessage = {
  type: "session_summary",
  total_score: 88.4,
  accuracy: 0.7,
  best_streak: 3,
  scored_lines: 3,
  hit_lines: 2,
};

/** The most recently created socket. */
export function lastSocket(
  sockets: readonly FakeSocket[] = FakeSocket.instances,
): FakeSocket {
  const socket = sockets.at(-1);
  if (socket === undefined) throw new Error("No socket was opened");
  return socket;
}
