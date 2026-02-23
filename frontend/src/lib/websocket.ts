type EventHandler = (data: unknown) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers: Map<string, Set<EventHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url: string | null = null;
  private token: string | null = null;
  private shouldReconnect = false;

  connect(sessionId: string, token: string): void {
    this.disconnect();
    this.token = token;
    this.url = `ws://localhost:8000/ws/design/${sessionId}?token=${encodeURIComponent(token)}`;
    this.shouldReconnect = true;
    this._open();
  }

  private _open(): void {
    if (!this.url) return;
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this._emit('connected', {});
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as { type: string; data: unknown };
        this._emit(msg.type, msg.data);
        this._emit('*', msg);
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this._emit('disconnected', {});
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this._open(), 3000);
      }
    };

    this.ws.onerror = () => {
      this._emit('error', {});
    };
  }

  on(event: string, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  private _emit(event: string, data: unknown): void {
    this.handlers.get(event)?.forEach((h) => h(data));
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

export const wsManager = new WebSocketManager();
