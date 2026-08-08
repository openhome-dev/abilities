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

// The extension's private storage dir — where we install a managed CLI venv when
// there's no workspace to install into (so voice/bridge work without a folder open).
let extStorageDir: string | undefined;
export function initCli(ctx: vscode.ExtensionContext): void {
  extStorageDir = ctx.globalStorageUri.fsPath;
}

/** Path to the openhome binary inside a `.venv` under baseDir. */
function venvOpenhome(baseDir: string): string {
  const rel =
    process.platform === "win32" ? ["Scripts", "openhome.exe"] : ["bin", "openhome"];
  return path.join(baseDir, ".venv", ...rel);
}

/**
 * Resolve the CLI command. Prefers a project `.venv` at/above the working dir,
 * then the extension's managed venv (works with no folder open), else the bare
 * `openhome` command from PATH.
 */
function autoDetectCli(cwd: string): string {
  let dir = cwd;
  for (let i = 0; i < 6 && dir; i++) {
    const candidate = venvOpenhome(dir);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  if (extStorageDir && fs.existsSync(venvOpenhome(extStorageDir))) {
    return venvOpenhome(extStorageDir);
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

const PY_VER = ["-c", "import sys;print(sys.version_info[0], sys.version_info[1])"];

function atLeast310(out: string): boolean {
  const m = out.trim().match(/(\d+)\s+(\d+)/);
  return !!m && (+m[1] > 3 || (+m[1] === 3 && +m[2] >= 10));
}

/**
 * Find a Python 3.10+ launcher. `openhome-client` requires >=3.10, and bare
 * `python3` is often an older system Python — so try versioned names first.
 * Returns the argv prefix (e.g. ["python3.12"] or ["py","-3.12"]) or undefined.
 */
async function findPython310(): Promise<string[] | undefined> {
  const candidates: string[][] =
    process.platform === "win32"
      ? [["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"], ["python"], ["py"]]
      : [["python3.13"], ["python3.12"], ["python3.11"], ["python3.10"], ["python3"], ["python"]];
  for (const c of candidates) {
    const r = await exec(c[0], [...c.slice(1), ...PY_VER]);
    if (r.code === 0 && atLeast310(r.out)) {
      return c;
    }
  }
  return undefined;
}

/** True if the given venv python is 3.10+. */
async function venvPy310(venvPy: string): Promise<boolean> {
  const r = await exec(venvPy, PY_VER);
  return r.code === 0 && atLeast310(r.out);
}

/**
 * Automatically set up the Python CLI with no prompts: reuse the workspace
 * `.venv` if present, otherwise create one, then `pip install openhome-client`
 * into it (the extension then auto-detects `.venv/bin/openhome`). Shows a
 * progress notification. Returns true on success.
 */
async function autoInstallCli(baseDir: string): Promise<boolean> {
  const isWin = process.platform === "win32";
  try {
    fs.mkdirSync(baseDir, { recursive: true });
  } catch {
    /* best effort */
  }
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "OpenHome: setting up the CLI", cancellable: false },
    async (progress) => {
      let venvPy = findVenvPython(baseDir);
      // Recreate the venv if it's missing or built with an old Python (<3.10),
      // which can't install openhome-client (requires >=3.10).
      if (!venvPy || !(await venvPy310(venvPy))) {
        progress.report({ message: "creating a virtual environment…" });
        try {
          fs.rmSync(path.join(baseDir, ".venv"), { recursive: true, force: true });
        } catch {
          /* best effort */
        }
        const py = await findPython310();
        if (!py) {
          vscode.window.showErrorMessage(
            "OpenHome: needs Python 3.10 or newer. Install it (macOS: `brew install python@3.12`) and try again."
          );
          return false;
        }
        const r = await exec(py[0], [...py.slice(1), "-m", "venv", ".venv"], baseDir);
        if (r.code !== 0) {
          vscode.window.showErrorMessage(
            `OpenHome: couldn't create a Python venv. ${r.out.trim().slice(-200)}`
          );
          return false;
        }
        venvPy = findVenvPython(baseDir);
      }
      if (!venvPy) {
        vscode.window.showErrorMessage("OpenHome: venv created but its Python wasn't found.");
        return false;
      }
      // Upgrade pip first — old pip (bundled with some Pythons) can't find wheels
      // for numpy/pyaudio and fails trying to build them from source.
      progress.report({ message: "upgrading pip…" });
      await exec(venvPy, ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], baseDir);

      // Install from the repo's cli/ (editable) when present, else from PyPI.
      const src = findCliSource(baseDir);
      const target = src ? ["-e", src] : ["openhome-client"];
      progress.report({
        message: src ? "installing the CLI from cli/ …" : "installing openhome-client from PyPI…",
      });
      const r = await exec(
        venvPy,
        ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", ...target],
        baseDir
      );
      if (r.code !== 0) {
        // Surface the actual error lines, not the trailing pip-version notice.
        const errLines = r.out
          .split("\n")
          .filter((l) => /error|failed|could not|no matching|not supported/i.test(l))
          .slice(-4)
          .join("  ");
        vscode.window.showErrorMessage(
          `OpenHome: pip install failed. ${errLines || r.out.trim().slice(-300)}`
        );
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
  // Install into the workspace if one is open, otherwise into the extension's
  // own storage so voice/bridge work even with no folder open.
  const baseDir = cwd || extStorageDir;
  if (!baseDir) {
    vscode.window.showErrorMessage("OpenHome: couldn't determine where to install the CLI.");
    return false;
  }

  if (!(await autoInstallCli(baseDir))) {
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
