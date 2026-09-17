// A websocket to the game server that reconnects automatically.

import type { ClientMessage, ServerMessage } from "./protocol";

export type ConnectionStatus = "connecting" | "open" | "closed";

export interface ConnectionHandlers {
  onOpen: () => void;
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: ConnectionStatus) => void;
}

export function serverUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws`;
}

export class GameConnection {
  private socket: WebSocket | null = null;
  private retryMs = 500;
  private readonly url: string;
  private readonly handlers: ConnectionHandlers;

  constructor(url: string, handlers: ConnectionHandlers) {
    this.url = url;
    this.handlers = handlers;
    this.connect();
  }

  /** Returns false if the socket is not open (the message is dropped). */
  send(message: ClientMessage): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  private connect(): void {
    this.handlers.onStatus("connecting");
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.retryMs = 500;
      this.handlers.onStatus("open");
      this.handlers.onOpen();
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      // `as` tells TypeScript what JSON.parse returned; it is not checked at runtime.
      // The server is ours, so we trust its shape.
      this.handlers.onMessage(JSON.parse(event.data) as ServerMessage);
    };
    socket.onclose = () => {
      this.handlers.onStatus("closed");
      setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, 5000);
    };
  }
}
