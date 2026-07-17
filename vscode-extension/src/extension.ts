import * as vscode from "vscode";
import * as api from "./api";
import { ensureCli, runInTerminal, runCliOrNotify } from "./cli";
import { AccountProvider, AbilitiesProvider, ActionsProvider, LocalProvider, Node } from "./trees";

const MIN_TRIGGER_LETTERS = 4;

/** Mirror the CLI's trigger-word validation so the UX matches. */
function triggerError(csv: string): string | undefined {
  const words = csv.split(",").map((w) => w.trim()).filter(Boolean);
  if (words.length === 0) {
    return "Enter at least one trigger word.";
  }
  for (const w of words) {
    const letters = (w.match(/[A-Za-z]/g) || []).length;
    if (letters === 0) {
      return `"${w}" must contain letters.`;
    }
    if (!/^[A-Za-z0-9 '\-]+$/.test(w)) {
      return `"${w}" has an invalid character (letters, numbers, spaces, ' and - only).`;
    }
    if (letters < MIN_TRIGGER_LETTERS) {
      return `"${w}" must contain at least ${MIN_TRIGGER_LETTERS} letters.`;
    }
  }
  return undefined;
}

export function activate(context: vscode.ExtensionContext): void {
  api.initApi(context.secrets);

  const account = new AccountProvider();
  const abilities = new AbilitiesProvider();
  const local = new LocalProvider();
  const voice = new ActionsProvider([
    { label: "Voice call an agent", command: "openhome.call", icon: "unmute", color: "charts.blue", tooltip: "Mic + speakers (opens a terminal — needs the CLI)" },
    { label: "Chat with an agent", command: "openhome.chat", icon: "comment-discussion", color: "charts.blue", tooltip: "Interactive text session (opens a terminal — needs the CLI)" },
    { label: "End call / session", command: "openhome.endCall", icon: "circle-slash", color: "charts.red", tooltip: "Hang up the active call or chat" },
  ]);

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("openhome.account", account),
    vscode.window.registerTreeDataProvider("openhome.abilities", abilities),
    vscode.window.registerTreeDataProvider("openhome.voice", voice),
    vscode.window.registerTreeDataProvider("openhome.local", local)
  );

  const refreshData = () => {
    account.refresh();
    abilities.refresh();
  };

  const reg = (id: string, fn: (...a: any[]) => any) =>
    context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  const report = async <T>(work: Promise<T>, ok?: string): Promise<T | undefined> => {
    try {
      const r = await work;
      if (ok) {
        vscode.window.showInformationMessage(ok);
      }
      return r;
    } catch (e) {
      if (e instanceof api.SessionExpiredError) {
        vscode.window.showErrorMessage(`OpenHome: ${e.message} Sign in again to refresh it.`);
      } else {
        vscode.window.showErrorMessage(`OpenHome: ${e instanceof Error ? e.message : String(e)}`);
      }
      return undefined;
    }
  };

  // ── Account / auth (native API, no CLI) ─────────────────────────────────
  reg("openhome.login", async () => {
    const apiKey = await vscode.window.showInputBox({
      title: "OpenHome API key",
      prompt: "Find it at app.openhome.com → Settings → API Keys",
      password: true,
      ignoreFocusOut: true,
    });
    if (!apiKey) {
      return;
    }
    const ok = await report(api.verifyApiKey(apiKey.trim()), undefined);
    if (ok === undefined) {
      return;
    }
    if (!ok) {
      vscode.window.showErrorMessage("OpenHome: that API key was rejected.");
      return;
    }
    await api.storeCredentials(apiKey.trim());
    vscode.window.showInformationMessage("OpenHome: signed in.");
    refreshData();
  });

  reg("openhome.logout", async () => {
    await api.clearCredentials();
    vscode.window.showInformationMessage("OpenHome: signed out.");
    refreshData();
  });

  reg("openhome.refreshAccount", () => account.refresh());
  reg("openhome.refreshAbilities", () => abilities.refresh());

  // ── Ability lifecycle ───────────────────────────────────────────────────
  const targetId = async (item?: Node): Promise<string | undefined> => {
    if (item?.abilityId) {
      return item.abilityId;
    }
    return vscode.window.showInputBox({ title: "Ability id or name", ignoreFocusOut: true });
  };

  reg("openhome.enable", async (item?: Node) => {
    const id = await targetId(item);
    if (id && (await report(api.setEnabled(id, true), `OpenHome: enabled ${id}.`)) !== undefined) {
      abilities.refresh();
    }
  });

  reg("openhome.disable", async (item?: Node) => {
    const id = await targetId(item);
    if (id && (await report(api.setEnabled(id, false), `OpenHome: disabled ${id}.`)) !== undefined) {
      abilities.refresh();
    }
  });

  reg("openhome.setTriggers", async (item?: Node) => {
    const id = await targetId(item);
    if (!id) {
      return;
    }
    const csv = await vscode.window.showInputBox({
      title: "Trigger words",
      prompt: "Comma-separated (each ≥4 letters)",
      ignoreFocusOut: true,
      validateInput: (v) => (v ? triggerError(v) : undefined),
    });
    if (!csv) {
      return;
    }
    const words = csv.split(",").map((w) => w.trim()).filter(Boolean);
    if ((await report(api.setTriggers(id, words), `OpenHome: updated triggers for ${id}.`)) !== undefined) {
      abilities.refresh();
    }
  });

  reg("openhome.delete", async (item?: Node) => {
    const id = await targetId(item);
    if (!id) {
      return;
    }
    const yes = await vscode.window.showWarningMessage(
      `Delete ability "${id}" from your account?`,
      { modal: true },
      "Delete"
    );
    if (yes !== "Delete") {
      return;
    }
    if ((await report(api.deleteAbility(id), `OpenHome: deleted ${id}.`)) !== undefined) {
      abilities.refresh();
    }
  });

  reg("openhome.openDashboard", () => {
    vscode.env.openExternal(vscode.Uri.parse("https://app.openhome.com"));
  });

  // Open a downloaded ability's main.py. Local folders (in user/, official/,
  // community/) carry a `.openhome.json` manifest linking them to a capability_id.
  reg("openhome.openAbility", async (id?: string, name?: string) => {
    const manifests = await vscode.workspace.findFiles(
      "**/.openhome.json",
      "**/{node_modules,.venv,.git}/**"
    );
    let byId: vscode.Uri | undefined;
    let byName: vscode.Uri | undefined;
    for (const m of manifests) {
      try {
        const raw = await vscode.workspace.fs.readFile(m);
        const mf = JSON.parse(Buffer.from(raw).toString("utf8"));
        const folder = vscode.Uri.joinPath(m, "..");
        if (id && String(mf.capability_id) === String(id)) {
          byId = folder;
          break;
        }
        if (name && mf.name === name) {
          byName = folder;
        }
      } catch {
        /* skip unreadable/invalid manifest */
      }
    }
    const folder = byId ?? byName;
    if (!folder) {
      const pick = await vscode.window.showInformationMessage(
        `"${name ?? id}" isn't downloaded locally yet.`,
        "Sync now"
      );
      if (pick === "Sync now") {
        vscode.commands.executeCommand("openhome.sync");
      }
      return;
    }
    const mainPy = vscode.Uri.joinPath(folder, "main.py");
    try {
      await vscode.workspace.fs.stat(mainPy);
    } catch {
      vscode.window.showWarningMessage(`No main.py found in ${folder.fsPath}.`);
      return;
    }
    const doc = await vscode.workspace.openTextDocument(mainPy);
    await vscode.window.showTextDocument(doc, { preview: false });
  });

  // Create / sync / push operate on local ability folders (scaffold + zip
  // upload), which the Python CLI already handles — so these stay CLI-backed.
  reg("openhome.create", async () => {
    if (!(await ensureCli())) {
      return;
    }
    const name = await vscode.window.showInputBox({
      title: "New ability name",
      prompt: "lowercase-with-hyphens",
      ignoreFocusOut: true,
      validateInput: (v) => (/^[a-z0-9-]+$/.test(v) ? undefined : "Use lowercase letters, numbers and hyphens."),
    });
    if (!name) {
      return;
    }
    const out = await runCliOrNotify(["create", name, "--no-push"]);
    if (out !== undefined) {
      vscode.window.showInformationMessage(out.trim() || `Created ${name}.`);
      abilities.refresh();
    }
  });

  reg("openhome.sync", async () => {
    if (!(await ensureCli())) {
      return;
    }
    if ((await runCliOrNotify(["sync"])) !== undefined) {
      vscode.window.showInformationMessage("OpenHome: synced abilities into user/.");
      abilities.refresh();
    }
  });

  reg("openhome.push", async () => {
    if (!(await ensureCli())) {
      return;
    }
    const folder = await vscode.window.showInputBox({
      title: "Push ability",
      prompt: "Path or name of the ability folder to push",
      ignoreFocusOut: true,
    });
    if (!folder) {
      return;
    }
    const out = await runCliOrNotify(["push", folder]);
    if (out !== undefined) {
      vscode.window.showInformationMessage(out.trim() || "Pushed.");
      abilities.refresh();
    }
  });

  // ── Voice (interactive → terminal, needs the CLI) ───────────────────────
  /**
   * Let the user pick an agent from their account. Returns the chosen id, ""
   * for the default agent, or undefined if cancelled. Falls back to a plain
   * input box if agents can't be fetched.
   */
  const pickAgent = async (title: string): Promise<string | undefined> => {
    let agents: api.Agent[] = [];
    try {
      agents = await api.listAgents();
    } catch {
      return vscode.window.showInputBox({
        title,
        prompt: "Agent id (blank = default agent)",
        ignoreFocusOut: true,
      });
    }
    const items: (vscode.QuickPickItem & { id: string })[] = [
      { label: "$(star) Default agent", description: "the account's default", id: "" },
      ...agents.map((a) => ({ label: `$(hubot) ${a.name || a.id}`, description: a.id, id: a.id })),
    ];
    const pick = await vscode.window.showQuickPick(items, {
      title,
      placeHolder: "Select an agent",
      matchOnDescription: true,
      ignoreFocusOut: true,
    });
    return pick?.id;
  };

  /** Accept an agent id (from a tree click) or a Node (from a menu). */
  const agentArg = (arg?: string | Node): string | undefined =>
    typeof arg === "string" ? arg : arg?.agentId;

  // Track the active interactive session (voice call / chat) so it can be ended
  // from the UI. The `openhome.inCall` context key toggles the End-call button.
  let activeSession: vscode.Terminal | undefined;
  const setSession = (term?: vscode.Terminal) => {
    activeSession = term;
    vscode.commands.executeCommand("setContext", "openhome.inCall", Boolean(term));
  };
  context.subscriptions.push(
    vscode.window.onDidCloseTerminal((t) => {
      if (t === activeSession) {
        setSession(undefined);
      }
    })
  );

  const startCall = async (agent: string) => {
    if (!(await ensureCli())) {
      return;
    }
    setSession(await runInTerminal("OpenHome Call", agent ? ["call", agent] : ["call"]));
  };

  const startChat = async (agent: string) => {
    if (!(await ensureCli())) {
      return;
    }
    setSession(await runInTerminal("OpenHome Chat", agent ? ["chat", agent] : ["chat"]));
  };

  reg("openhome.endCall", () => {
    if (activeSession) {
      activeSession.dispose(); // kills the CLI process (it's the terminal's root process)
      setSession(undefined);
      vscode.window.showInformationMessage("OpenHome: ended the session.");
    } else {
      vscode.window.showInformationMessage("OpenHome: no active call or chat.");
    }
  });

  // Direct call/chat for a specific agent (tree click or inline button).
  reg("openhome.callAgent", async (arg?: string | Node) => {
    const id = agentArg(arg);
    if (id !== undefined) {
      await startCall(id);
    }
  });

  reg("openhome.chatAgent", async (arg?: string | Node) => {
    const id = agentArg(arg);
    if (id !== undefined) {
      await startChat(id);
    }
  });

  // Voice/Chat buttons in the Voice section: pick an agent, then launch.
  reg("openhome.call", async () => {
    const agent = await pickAgent("Voice call an agent");
    if (agent !== undefined) {
      await startCall(agent);
    }
  });

  reg("openhome.chat", async () => {
    const agent = await pickAgent("Chat with an agent");
    if (agent !== undefined) {
      await startChat(agent);
    }
  });

  // ── Local bridge (devkit, needs the CLI) ────────────────────────────────
  reg("openhome.localStart", async () => {
    if (!(await ensureCli())) {
      return;
    }
    if ((await runCliOrNotify(["local", "start"])) !== undefined) {
      vscode.window.showInformationMessage("OpenHome: local bridge started.");
    }
    local.refresh();
  });

  reg("openhome.localStop", async () => {
    if (!(await ensureCli())) {
      return;
    }
    if ((await runCliOrNotify(["local", "stop"])) !== undefined) {
      vscode.window.showInformationMessage("OpenHome: local bridge stopped.");
    }
    local.refresh();
  });

  reg("openhome.localStatus", () => local.refresh());

  reg("openhome.localLogs", async () => {
    if (!(await ensureCli())) {
      return;
    }
    await runInTerminal("OpenHome Bridge Logs", ["local", "logs"]);
  });
}

export function deactivate(): void {}
