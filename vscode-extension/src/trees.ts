import * as vscode from "vscode";
import * as api from "./api";
import { runCli } from "./cli";

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
        n.description = a.isInstalled ? "installed" : "not installed";
        n.tooltip = [
          `id: ${a.id}`,
          `category: ${a.category ?? "—"}`,
          `triggers: ${a.triggerWords.join(", ") || "—"}`,
        ].join("\n");
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
 * Local Bridge (Devkit) view: a colored status row on top, then the actions.
 * Today the status comes from `openhome local status`; this is the hook where a
 * live socket will later drive the green/red indicator.
 */
export class LocalProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private readonly actions = [
    { label: "Start bridge", command: "openhome.localStart", icon: "play", color: "charts.green" },
    { label: "Stop bridge", command: "openhome.localStop", icon: "debug-stop", color: "charts.red" },
    { label: "Show status", command: "openhome.localStatus", icon: "pulse", color: "charts.blue" },
    { label: "View logs", command: "openhome.localLogs", icon: "output", color: "charts.yellow" },
  ];

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(el: Node): vscode.TreeItem {
    return el;
  }

  async getChildren(): Promise<Node[]> {
    const res = await runCli(["local", "status"]);
    const out = (res.stdout + res.stderr).toLowerCase();
    const running = res.code === 0 && out.includes("running") && !out.includes("not running");
    const status = new Node(running ? "Devkit: connected" : "Devkit: offline");
    status.iconPath = new vscode.ThemeIcon(
      running ? "circle-filled" : "circle-outline",
      new vscode.ThemeColor(running ? "testing.iconPassed" : "testing.iconFailed")
    );
    status.tooltip = (res.stdout || res.stderr || "").trim() || "openhome local status";

    const actionNodes = this.actions.map((a) => {
      const n = new Node(a.label);
      n.command = { command: a.command, title: a.label };
      n.iconPath = new vscode.ThemeIcon(a.icon, new vscode.ThemeColor(a.color));
      return n;
    });
    return [status, ...actionNodes];
  }
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
