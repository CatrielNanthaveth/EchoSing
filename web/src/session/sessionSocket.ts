import type {
  ClientMessage,
  ErrorMessage,
  LinePitchMessage,
  LineScoreMessage,
  ServerMessage,
  SessionSummaryMessage,
} from "../api/types";

/** Close codes defined by the server (docs/ws-protocol.md). */
export const CLOSE_SESSION_NOT_FOUND = 4404;
export const CLOSE_SESSION_FINISHED = 4409;

const RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000];

export type SocketStatus = "connecting" | "open" | "reconnecting" | "closed" | "failed";

export interface SessionSocketEvents {
  onScore?: (score: LineScoreMessage) => void;
  onError?: (error: ErrorMessage) => void;
  onStatus?: (status: SocketStatus) => void;
}

type SocketFactory = (url: string) => WebSocket;

/**
 * Real-time scoring connection of a play session.
 *
 * Lines are queued in order and kept until the server scores them, so a
 * dropped connection loses nothing: after reconnecting, the `ready` message
 * says which lines were scored and the others are sent again.
 */
export class SessionSocket {
  readonly #url: string;
  readonly #events: SessionSocketEvents;
  readonly #createSocket: SocketFactory;
  /** Lines sent or waiting, until scored. */
  readonly #pending = new Map<number, LinePitchMessage>();
  #socket: WebSocket | null = null;
  #ready = false;
  #attempt = 0;
  #closed = false;
  #retryTimer: ReturnType<typeof setTimeout> | null = null;
  #finishing: {
    resolve: (summary: SessionSummaryMessage) => void;
    reject: (error: Error) => void;
  } | null = null;

  constructor(
    url: string,
    events: SessionSocketEvents = {},
    createSocket: SocketFactory = (target) => new WebSocket(target),
  ) {
    this.#url = url;
    this.#events = events;
    this.#createSocket = createSocket;
    this.#connect();
  }

  /** Send the pitch sung over a line (queued while disconnected). */
  sendLine(message: Omit<LinePitchMessage, "type">): void {
    const line: LinePitchMessage = { type: "line_pitch", ...message };
    this.#pending.set(line.line_index, line);
    if (this.#ready) this.#send(line);
  }

  /**
   * Finish the session once every pending line is scored.
   *
   * @returns The final totals.
   */
  finish(): Promise<SessionSummaryMessage> {
    if (this.#closed) return Promise.reject(new Error("La sesión ya está cerrada"));
    return new Promise((resolve, reject) => {
      this.#finishing = { resolve, reject };
      if (this.#ready) this.#send({ type: "finish" });
    });
  }

  /** Close without finishing (e.g. the player stopped the song). */
  close(): void {
    this.#shutDown("closed");
    this.#finishing?.reject(new Error("La sesión se cerró antes de terminar"));
    this.#finishing = null;
  }

  #connect(): void {
    this.#ready = false;
    this.#events.onStatus?.(this.#attempt === 0 ? "connecting" : "reconnecting");
    const socket = this.#createSocket(this.#url);
    this.#socket = socket;
    socket.onmessage = (event: MessageEvent<string>) => {
      this.#receive(JSON.parse(event.data) as ServerMessage);
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.#socket !== socket || this.#closed) return;
      this.#onDisconnect(event.code);
    };
  }

  #receive(message: ServerMessage): void {
    switch (message.type) {
      case "ready":
        this.#attempt = 0;
        this.#ready = true;
        this.#events.onStatus?.("open");
        for (const index of message.scored_lines) this.#pending.delete(index);
        for (const line of this.#pending.values()) this.#send(line);
        if (this.#finishing !== null) this.#send({ type: "finish" });
        break;
      case "line_score":
        this.#pending.delete(message.line_index);
        this.#events.onScore?.(message);
        break;
      case "error":
        // Scored before a reconnection: nothing left to send for that line.
        if (message.code === "line_already_scored") {
          const index = /Line (\d+)/.exec(message.detail)?.[1];
          if (index !== undefined) this.#pending.delete(Number(index));
        }
        this.#events.onError?.(message);
        break;
      case "session_summary":
        this.#finishing?.resolve(message);
        this.#finishing = null;
        this.#shutDown("closed");
        break;
    }
  }

  #onDisconnect(code: number): void {
    this.#ready = false;
    const fatal = code === CLOSE_SESSION_NOT_FOUND || code === CLOSE_SESSION_FINISHED;
    const delay = RECONNECT_DELAYS_MS[this.#attempt];
    if (fatal || delay === undefined) {
      this.#shutDown("failed");
      this.#finishing?.reject(new Error("Se perdió la conexión con el servidor"));
      this.#finishing = null;
      return;
    }
    this.#attempt++;
    this.#events.onStatus?.("reconnecting");
    this.#retryTimer = setTimeout(() => {
      this.#connect();
    }, delay);
  }

  #send(message: ClientMessage): void {
    this.#socket?.send(JSON.stringify(message));
  }

  #shutDown(status: SocketStatus): void {
    if (this.#closed) return;
    this.#closed = true;
    this.#ready = false;
    if (this.#retryTimer !== null) clearTimeout(this.#retryTimer);
    const socket = this.#socket;
    this.#socket = null;
    if (socket !== null && socket.readyState <= WebSocket.OPEN) socket.close();
    this.#events.onStatus?.(status);
  }
}
