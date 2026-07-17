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

/**
 * Find the local CLI source (the `cli/` folder with pyproject.toml + openhome
 * package) at/above cwd. `openhome-client` isn't on PyPI, so we install from
 * here in editable mode; only fall back to PyPI if it's ever published.
 */
function findCliSource(cwd: string): string | undefined {
  let dir = cwd;
  for (let i = 0; i < 6 && dir; i++) {
    for (const cand of [path.join(dir, "cli"), dir]) {
      if (
        fs.existsSync(path.join(cand, "pyproject.toml")) &&
        fs.existsSync(path.join(cand, "openhome"))
      ) {
        return cand;
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  return undefined;
}

/** Find a Python interpreter inside a `.venv` at/above cwd (for installing into). */
function findVenvPython(cwd: string): string | undefined {
  const rel = process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"];
  let dir = cwd;
  for (let i = 0; i < 6 && dir; i++) {
    const candidate = path.join(dir, ".venv", ...rel);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  return undefined;
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
export async function runInTerminal(name: string, args: string[]): Promise<vscode.Terminal> {
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
  return term;
}

/** Run a command to completion, capturing combined output (for setup steps). */
function exec(cmd: string, args: string[], cwd?: string): Promise<{ code: number; out: string }> {
  return new Promise((resolve) => {
    let out = "";
    const child = spawn(cmd, args, { cwd, shell: false });
    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (out += d.toString()));
    child.on("error", (e) => resolve({ code: 127, out: out + String(e) }));
    child.on("close", (code) => resolve({ code: code ?? 1, out }));
  });
}

/**
 * Automatically set up the Python CLI with no prompts: reuse the workspace
 * `.venv` if present, otherwise create one, then `pip install openhome-client`
 * into it (the extension then auto-detects `.venv/bin/openhome`). Shows a
 * progress notification. Returns true on success.
 */
async function autoInstallCli(cwd: string): Promise<boolean> {
  const isWin = process.platform === "win32";
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "OpenHome: setting up the CLI", cancellable: false },
    async (progress) => {
      let venvPy = findVenvPython(cwd);
      if (!venvPy) {
        progress.report({ message: "creating a virtual environment…" });
        let r = await exec(isWin ? "python" : "python3", ["-m", "venv", ".venv"], cwd);
        if (r.code !== 0 && !isWin) {
          r = await exec("python", ["-m", "venv", ".venv"], cwd); // some distros only have `python`
        }
        if (r.code !== 0) {
          vscode.window.showErrorMessage(
            `OpenHome: couldn't create a Python venv — install Python 3, or set openhome.cliPath. ${r.out.trim().slice(-200)}`
          );
          return false;
        }
        venvPy = findVenvPython(cwd);
      }
      if (!venvPy) {
        vscode.window.showErrorMessage("OpenHome: venv created but its Python wasn't found.");
        return false;
      }
      // openhome-client isn't on PyPI — install editable from the repo's cli/ if
      // present; otherwise try PyPI (works only once/if it's published there).
      const src = findCliSource(cwd);
      const target = src ? ["-e", src] : ["openhome-client"];
      progress.report({
        message: src ? "installing the CLI from cli/ …" : "installing openhome-client…",
      });
      const r = await exec(venvPy, ["-m", "pip", "install", "--upgrade", ...target], cwd);
      if (r.code !== 0) {
        const hint = src
          ? ""
          : " (openhome-client isn't on PyPI — open the OpenHome/abilities repo so it can install from cli/).";
        vscode.window.showErrorMessage(`OpenHome: pip install failed.${hint} ${r.out.trim().slice(-260)}`);
        return false;
      }
      return true;
    }
  );
}

/**
 * Ensure the CLI is runnable. No-op if it's already found (venv or PATH). If
 * missing, it auto-installs into a workspace venv and retries — no dialogs.
 * Voice calls and the local bridge need the Python CLI (mic/audio/daemon); the
 * account and ability features use the API and never call this. All failure
 * paths return false and surface a message rather than throwing.
 */
export async function ensureCli(): Promise<boolean> {
  let res: CliResult;
  try {
    res = await runCli(["--help"]);
  } catch (e) {
    vscode.window.showErrorMessage(`OpenHome: couldn't run the CLI (${String(e)}).`);
    return false;
  }
  if (!(res.code === 127 || /ENOENT/.test(res.stderr))) {
    return true;
  }

  const { cwd } = cliConfig();
  if (!cwd) {
    const pick = await vscode.window.showWarningMessage(
      "OpenHome CLI not found, and no folder is open to install it into. Open your OpenHome/abilities folder, or set the CLI path.",
      "Set path…"
    );
    if (pick === "Set path…") {
      await vscode.commands.executeCommand("workbench.action.openSettings", "openhome.cliPath");
    }
    return false;
  }

  if (!(await autoInstallCli(cwd))) {
    return false;
  }
  res = await runCli(["--help"]); // re-check now that it should be installed
  if (res.code === 0) {
    vscode.window.showInformationMessage("OpenHome: CLI ready.");
    return true;
  }
  vscode.window.showWarningMessage(
    "OpenHome: CLI installed but couldn't be launched. Set openhome.cliPath to the venv's openhome binary."
  );
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
