import type { WsEvent } from "./types";

interface Handlers {
  onEvent: (event: WsEvent) => void;
  onOpen?: () => void;
  onReconnect?: () => void;
  onClose?: () => void;
  onError?: (message: string) => void;
}

const RECONNECT_DELAYS = [1000, 2000, 5000];

export class MiraSocket {
  private ws: WebSocket | null = null;
  private closedByUser = false;
  private reconnectAttempt = 0;
  private retryTimer: number | null = null;

  constructor(
    private readonly url: string,
    private readonly handlers: Handlers,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      const reconnected = this.reconnectAttempt > 0;
      this.reconnectAttempt = 0;
      this.handlers.onOpen?.();
      if (reconnected) {
        // The socket dropped and came back: events sent while we were away
        // are lost, so the consumer should resync from the server.
        this.handlers.onReconnect?.();
      }
    };

    ws.onmessage = (event) => {
      try {
        this.handlers.onEvent(JSON.parse(event.data as string) as WsEvent);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      this.handlers.onClose?.();
      if (!this.closedByUser && this.reconnectAttempt < RECONNECT_DELAYS.length) {
        const delay = RECONNECT_DELAYS[this.reconnectAttempt];
        this.reconnectAttempt += 1;
        this.retryTimer = window.setTimeout(() => this.open(), delay);
      }
    };

    ws.onerror = () => {
      this.handlers.onError?.("connection error");
    };
  }

  sendText(content: string): void {
    this.send({ type: "text", content });
  }

  sendImage(image: string, caption = ""): void {
    this.send({ type: "image", image, caption });
  }

  send(payload: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  close(): void {
    this.closedByUser = true;
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
    }
    this.ws?.close();
    this.ws = null;
  }
}
