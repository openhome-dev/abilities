import * as vscode from "vscode";
import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { cliEnv } from "./api";

export interface CliResult {
  code: number;
  stdout: string;
  stderr: string;
}

/**
 * When the user hasn't set a path, look for a project virtualenv's openhome
 * binary next to (or above) the working directory, so it works out of the box
 * without the CLI being on PATH. Falls back to the bare `openhome` command.
 */
function autoDetectCli(cwd: string): string {
  const binName = process.platform === "win32" ? "openhome.exe" : "openhome";
  const venvRel = process.platform === "win32" ? ["Scripts", binName] : ["bin", binName];
  let dir = cwd;
  for (let i = 0; i < 6 && dir; i++) {
    const candidate = path.join(dir, ".venv", ...venvRel);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  return "openhome";
}

/** Resolve the configured CLI command and working directory. */
function cliConfig(): { cmd: string; cwd: string | undefined } {
  const cfg = vscode.workspace.getConfiguration("openhome");
  let cwd = cfg.get<string>("cwd") || "";
  if (!cwd) {
    cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
  }
  // An explicit cliPath setting always wins; otherwise auto-detect a venv.
  const configured = cfg.get<string>("cliPath");
  const cmd = configured && configured !== "openhome" ? configured : autoDetectCli(cwd);
  return { cmd, cwd: cwd || undefined };
}

/**
 * Run the OpenHome CLI non-interactively and capture its output.
 * Used for the data/lifecycle commands (list, agents, enable, ...).
 */
export async function runCli(args: string[]): Promise<CliResult> {
  const { cmd, cwd } = cliConfig();
  const env = { ...process.env, ...(await cliEnv()) };
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    const child = spawn(cmd, args, { cwd, shell: false, env });
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));
    child.on("error", (err) => {
      resolve({ code: 127, stdout, stderr: stderr + String(err) });
    });
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

/** Run the CLI and surface stderr to the user on failure. Returns stdout. */
export async function runCliOrNotify(args: string[]): Promise<string | undefined> {
  const res = await runCli(args);
  if (res.code !== 0) {
    const msg = (res.stderr || res.stdout || `exit ${res.code}`).trim();
    vscode.window.showErrorMessage(`openhome ${args[0] ?? ""}: ${msg}`);
    return undefined;
  }
  return res.stdout;
}

/**
 * Run an interactive CLI command (voice call, chat, bridge run) in a VS Code
 * terminal — these need a TTY / mic / speakers, so they can't be captured.
 */
export async function runInTerminal(name: string, args: string[]): Promise<void> {
  const { cmd, cwd } = cliConfig();
  // Launch the CLI as the terminal's ROOT process (not typed into a shell).
  // This avoids the shell/Python-extension env-activation race, which injects a
  // Ctrl-C into the terminal to clear the prompt — that SIGINT was killing live
  // voice calls mid-stream. With shellPath there's no shell to activate into,
  // and the process gets a real TTY (so SPACE / Ctrl-C still work).
  const term = vscode.window.createTerminal({
    name,
    cwd,
    shellPath: cmd,
    shellArgs: args,
    env: await cliEnv(),
  });
  term.show();
}

/**
 * Check that the CLI is runnable; if not, offer to install it. Voice calls and
 * the local bridge need the Python CLI (mic/audio/daemon) — the account and
 * ability features talk to the API directly and don't require it.
 */
export async function ensureCli(): Promise<boolean> {
  const res = await runCli(["--help"]);
  const missing = res.code === 127 || /ENOENT/.test(res.stderr);
  if (!missing) {
    return true;
  }
  const pick = await vscode.window.showWarningMessage(
    "This feature needs the OpenHome CLI (Python), which wasn't found. Install it now?",
    "Install CLI",
    "Set path…"
  );
  if (pick === "Install CLI") {
    const { cwd } = cliConfig();
    const term = vscode.window.createTerminal({ name: "Install OpenHome CLI", cwd });
    term.sendText("pip install openhome-client");
    term.show();
    vscode.window.showInformationMessage(
      "Installing the OpenHome CLI in the terminal. Once it finishes, retry the action."
    );
  } else if (pick === "Set path…") {
    await vscode.commands.executeCommand("workbench.action.openSettings", "openhome.cliPath");
  }
  return false;
}

/** Split tab-separated CLI output into non-empty rows of columns. */
export function parseRows(stdout: string): string[][] {
  return stdout
    .split("\n")
    .map((l) => l.trimEnd())
    .filter((l) => l.length > 0)
    .map((l) => l.split("\t"));
}
