import * as vscode from "vscode";
import * as api from "./api";
import { DevkitMonitor, DevkitStats } from "./devkit";

/** A simple tree node — either a data row or a clickable action. */
export class Node extends vscode.TreeItem {
  abilityId?: string;
  agentId?: string;
  constructor(
    label: string,
    collapsible: vscode.TreeItemCollapsibleState = vscode.TreeItemCollapsibleState.None
  ) {
    super(label, collapsible);
  }
}

function loginPrompt(label: string): Node {
  const n = new Node(label);
  n.iconPath = new vscode.ThemeIcon("warning");
  n.command = { command: "openhome.login", title: "Login" };
  return n;
}

/** Account view: shows login state and lists the account's agents. */
export class AccountProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(el: Node): vscode.TreeItem {
    return el;
  }

  async getChildren(): Promise<Node[]> {
    if (!(await api.isConfigured())) {
      return [loginPrompt("Not signed in — click the sign-in icon")];
    }
    try {
      const agents = await api.listAgents();
      if (agents.length === 0) {
        return [new Node("No agents on this account")];
      }
      return agents.map((a) => {
        const n = new Node(a.name || a.id);
        n.iconPath = new vscode.ThemeIcon("account", new vscode.ThemeColor("charts.purple"));
        n.tooltip = `${a.description || a.name}\n\nClick to voice call · agent id: ${a.id}`;
        n.contextValue = "agent";
        n.agentId = a.id;
        // Clicking an agent starts a voice call with it.
        n.command = { command: "openhome.callAgent", title: "Voice call", arguments: [a.id] };
        return n;
      });
    } catch (e) {
      return [errorNode(e)];
    }
  }
}

/** Abilities view: lists the account's abilities with install state + triggers. */
export class AbilitiesProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(el: Node): vscode.TreeItem {
    return el;
  }

  async getChildren(): Promise<Node[]> {
    if (!(await api.isConfigured())) {
      return [loginPrompt("Sign in to list abilities")];
    }
    try {
      const abilities = await api.listAbilities();
      if (abilities.length === 0) {
        return [new Node("No abilities on this account")];
      }
      return abilities.map((a) => {
        const n = new Node(a.name || a.id);
        const triggers = a.triggerWords.join(", ");
        // Show the trigger phrases inline (that's how you invoke it in a call).
        n.description = triggers
          ? `🗣 ${triggers}`
          : a.isInstalled
          ? "installed"
          : "not installed";
        const md = new vscode.MarkdownString();
        md.appendMarkdown(`**${a.name || a.id}**  ·  _${a.isInstalled ? "installed" : "not installed"}_\n\n`);
        md.appendMarkdown(`**Trigger words:**\n`);
        if (a.triggerWords.length) {
          md.appendMarkdown(a.triggerWords.map((w) => `- “${w}”`).join("\n"));
        } else {
          md.appendMarkdown("_none set_");
        }
        md.appendMarkdown(`\n\ncategory: ${a.category ?? "—"} · id: ${a.id}`);
        n.tooltip = md;
        n.iconPath = new vscode.ThemeIcon(
          a.isInstalled ? "plug" : "circle-outline",
          new vscode.ThemeColor(a.isInstalled ? "charts.green" : "disabledForeground")
        );
        n.contextValue = "ability";
        n.abilityId = a.id;
        // Clicking an ability opens its local main.py (if downloaded).
        n.command = { command: "openhome.openAbility", title: "Open code", arguments: [a.id, a.name] };
        return n;
      });
    } catch (e) {
      return [errorNode(e)];
    }
  }
}

function errorNode(e: unknown): Node {
  if (e instanceof api.NotAuthenticatedError || e instanceof api.SessionExpiredError) {
    return loginPrompt(e.message);
  }
  const n = new Node(e instanceof Error ? e.message : String(e));
  n.iconPath = new vscode.ThemeIcon("error");
  return n;
}

/**
 * Devkit view: a colored status row driven by the live monitoring socket, the
 * latest device stats when connected, and a single Connect/Disconnect action
 * that flips with the connection state.
 */
export class LocalProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private readonly monitor: DevkitMonitor) {
    // Re-render whenever the socket state or stats change.
    monitor.onDidChange(() => this._onDidChange.fire());
  }

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(el: Node): vscode.TreeItem {
    return el;
  }

  getChildren(): Node[] {
    const state = this.monitor.state;
    const status = new Node(
      state === "online" ? "Devkit: connected" : state === "connecting" ? "Devkit: connecting…" : "Devkit: offline"
    );
    const icon =
      state === "online"
        ? { name: "circle-filled", color: "testing.iconPassed" }
        : state === "connecting"
        ? { name: "loading~spin", color: "charts.yellow" }
        : { name: "circle-outline", color: "testing.iconFailed" };
    status.iconPath = new vscode.ThemeIcon(icon.name, new vscode.ThemeColor(icon.color));
    status.tooltip = this.monitor.detail;

    const rows: Node[] = [status, ...statRows(this.monitor.stats, state)];

    // Connect when offline; Disconnect otherwise — never both.
    if (state === "offline") {
      const connect = new Node("Connect");
      connect.command = { command: "openhome.devkitConnect", title: "Connect" };
      connect.iconPath = new vscode.ThemeIcon("plug", new vscode.ThemeColor("charts.green"));
      rows.push(connect);
    } else {
      const disconnect = new Node("Disconnect");
      disconnect.command = { command: "openhome.devkitDisconnect", title: "Disconnect" };
      disconnect.iconPath = new vscode.ThemeIcon("debug-disconnect", new vscode.ThemeColor("charts.red"));
      rows.push(disconnect);
    }
    return rows;
  }
}

/** Format a used/total metric like "9% (1215/3841 MB)". */
function pct(m?: { used: number; total: number; unit: string }): string | undefined {
  if (!m || !m.total) {
    return undefined;
  }
  const p = Math.round((m.used / m.total) * 100);
  const unit = m.unit === "%" ? "" : ` ${m.unit}`;
  return m.unit === "%" ? `${m.used}%` : `${p}% (${m.used}/${m.total}${unit})`;
}

/** Read-only rows describing the current device, shown only when online. */
function statRows(stats: DevkitStats | undefined, state: string): Node[] {
  if (state !== "online" || !stats) {
    return [];
  }
  const items: { label: string; value?: string; icon: string }[] = [
    { label: "CPU", value: pct(stats.cpu), icon: "pulse" },
    { label: "RAM", value: pct(stats.ram), icon: "server" },
    { label: "Disk", value: pct(stats.disk), icon: "database" },
    { label: "Firmware", value: stats.firmwareVersion, icon: "chip" },
    { label: "IP", value: stats.ipAddress, icon: "globe" },
    { label: "MQTT", value: stats.mqttRunning ? "running" : "stopped", icon: "broadcast" },
    { label: "Agent", value: stats.agentConnected ? "connected" : "disconnected", icon: "hubot" },
  ];
  return items
    .filter((i) => i.value !== undefined)
    .map((i) => {
      const n = new Node(i.label);
      n.description = i.value;
      n.iconPath = new vscode.ThemeIcon(i.icon, new vscode.ThemeColor("charts.blue"));
      return n;
    });
}

interface Action {
  label: string;
  command: string;
  icon: string;
  color?: string;
  tooltip?: string;
}

/** Static list of clickable actions (used for the Voice view). */
export class ActionsProvider implements vscode.TreeDataProvider<Node> {
  constructor(private readonly actions: Action[]) {}

  getTreeItem(el: Node): vscode.TreeItem {
    return el;
  }

  getChildren(): Node[] {
    return this.actions.map((a) => {
      const n = new Node(a.label);
      n.command = { command: a.command, title: a.label };
      n.iconPath = new vscode.ThemeIcon(a.icon, a.color ? new vscode.ThemeColor(a.color) : undefined);
      if (a.tooltip) {
        n.tooltip = a.tooltip;
      }
      return n;
    });
  }
}
