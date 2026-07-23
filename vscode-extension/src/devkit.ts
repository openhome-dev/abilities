import * as vscode from "vscode";
import WebSocket from "ws";
import { getDevkitSocketUrl } from "./api";

/**
 * offline    — no socket (signed out, disconnected, or connection failed)
 * connecting — socket opening, or open but the physical device isn't reporting yet
 * online     — the device is connected and streaming stats
 */
export type DevkitState = "offline" | "connecting" | "online";

interface Metric {
  used: number;
  total: number;
  unit: string;
}

/** The subset of a `device_stats` payload we surface in the tree. */
export interface DevkitStats {
  firmwareVersion?: string;
  ipAddress?: string;
  cpu?: Metric;
  ram?: Metric;
  disk?: Metric;
  mqttRunning?: boolean;
  agentConnected?: boolean;
  isLocalMode?: boolean;
  timestamp?: string;
}

const POLL_MS = 20_000; // matches the web dashboard's device_stats cadence
const MAX_BACKOFF_MS = 30_000;

/**
 * Maintains the live devkit WebSocket and exposes the latest connection state
 * and device stats. On open it identifies as the "frontend" client (as the web
 * dashboard does), then polls `device_stats`. Reconnects with backoff. This is
 * the hook that drives the green/red indicator in the Devkit view.
 */
export class DevkitMonitor {
  private ws?: WebSocket;
  private _state: DevkitState = "offline";
  private _stats?: DevkitStats;
  private _detail = "Not connected.";
  private pollTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private attempts = 0;
  private manualDisconnect = false;
  private disposed = false;

  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChange = this._onDidChange.event;

  get state(): DevkitState {
    return this._state;
  }
  get stats(): DevkitStats | undefined {
    return this._stats;
  }
  get detail(): string {
    return this._detail;
  }

  /** Open the socket (no-op if already connecting/online). */
  async connect(): Promise<void> {
    if (this.disposed || this.ws) {
      return;
    }
    const url = await getDevkitSocketUrl();
    if (!url) {
      this.set("offline", "Sign in to connect to your devkit.");
      return;
    }
    this.manualDisconnect = false;
    this.set("connecting", "Connecting…");

    let sock: WebSocket;
    try {
      sock = new WebSocket(url, { handshakeTimeout: 10_000 });
    } catch (e) {
      this.set("offline", `Couldn't open socket: ${String(e)}`);
      this.scheduleReconnect();
      return;
    }
    this.ws = sock;

    sock.on("open", () => {
      this.attempts = 0;
      this.set("connecting", "Connected to cloud — waiting for device…");
      this.send("frontend"); // identify as the dashboard client, not the device
      this.requestStats();
      this.pollTimer = setInterval(() => this.requestStats(), POLL_MS);
    });
    sock.on("message", (data) => this.onMessage(data.toString()));
    sock.on("error", (err) => {
      this._detail = `Socket error: ${err.message}`;
    });
    sock.on("close", () => {
      this.teardownSocket();
      if (this.disposed || this.manualDisconnect) {
        this.set("offline", "Disconnected.");
        return;
      }
      this.scheduleReconnect();
    });
  }

  /** Close the socket and stop reconnecting until connect() is called again. */
  disconnect(): void {
    this.manualDisconnect = true;
    this.clearReconnect();
    this.teardownSocket();
    this._stats = undefined;
    this.set("offline", "Disconnected.");
  }

  /** Drop the current socket and immediately reconnect (e.g. after re-login). */
  async reconnect(): Promise<void> {
    this.clearReconnect();
    this.teardownSocket();
    this.attempts = 0;
    await this.connect();
  }

  dispose(): void {
    this.disposed = true;
    this.clearReconnect();
    this.teardownSocket();
    this._onDidChange.dispose();
  }

  // ── internals ─────────────────────────────────────────────────────────────

  private onMessage(raw: string): void {
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return; // ignore non-JSON frames
    }
    if (typeof msg?.device_status === "string") {
      if (msg.device_status === "connected") {
        this.set("online", "Devkit connected.");
      } else {
        this.set("connecting", `Device ${msg.device_status}.`);
      }
      return;
    }
    if (msg?.response === "device_stats" && msg.data) {
      this._stats = parseStats(msg.data);
      this.set("online", `Devkit connected · updated ${this._stats.timestamp ?? "just now"}`);
    }
  }

  private requestStats(): void {
    this.send(JSON.stringify({ command: "device_stats" }));
  }

  private send(payload: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(payload);
      } catch {
        /* the close handler will drive reconnect */
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.manualDisconnect || this.reconnectTimer) {
      return;
    }
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempts);
    this.attempts++;
    this.set("connecting", `Reconnecting in ${Math.round(delay / 1000)}s…`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.connect();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
  }

  private teardownSocket(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
    if (this.ws) {
      this.ws.removeAllListeners();
      try {
        this.ws.terminate();
      } catch {
        /* best effort */
      }
      this.ws = undefined;
    }
  }

  private set(state: DevkitState, detail: string): void {
    const changed = state !== this._state || detail !== this._detail;
    this._state = state;
    this._detail = detail;
    if (changed) {
      this._onDidChange.fire();
    }
  }
}

function metric(m: any): Metric | undefined {
  if (!m || typeof m.total !== "number") {
    return undefined;
  }
  return { used: Number(m.used) || 0, total: Number(m.total) || 0, unit: String(m.unit ?? "") };
}

function parseStats(data: any): DevkitStats {
  const hw = data.hardware_stats ?? {};
  return {
    firmwareVersion: data.firmware_version,
    ipAddress: data.ip_address,
    cpu: metric(hw.cpu),
    ram: metric(hw.ram),
    disk: metric(hw.disk),
    mqttRunning: Boolean(data.mqtt?.running),
    agentConnected: Boolean(data.agent_stats?.connected),
    isLocalMode: Boolean(data.is_local_mode),
    timestamp: data.timestamp,
  };
}
