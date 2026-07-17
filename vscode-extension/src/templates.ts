import * as vscode from "vscode";

const DEFAULT_REPO = "openhome-dev/abilities";
const DEFAULT_REF = "main";

export interface Template {
  name: string;
  source: "template" | "official";
  path: string; // repo path, e.g. "templates/basic-template"
}

function cfg(): { repo: string; ref: string } {
  const c = vscode.workspace.getConfiguration("openhome");
  return {
    repo: c.get<string>("templatesRepo") || DEFAULT_REPO,
    ref: c.get<string>("templatesRef") || DEFAULT_REF,
  };
}

/** Call the GitHub Contents API for a repo path, returning the JSON entries. */
async function ghContents(repoPath: string): Promise<any[]> {
  const { repo, ref } = cfg();
  const url = `https://api.github.com/repos/${repo}/contents/${repoPath}?ref=${ref}`;
  const resp = await fetch(url, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "openhome-vscode" },
  });
  if (resp.status === 403) {
    throw new Error("GitHub API rate limit reached — please try again in a few minutes.");
  }
  if (!resp.ok) {
    throw new Error(`GitHub returned ${resp.status} for ${repoPath}`);
  }
  const data = await resp.json();
  return Array.isArray(data) ? data : [];
}

/** List the available templates (templates/ + official/) for the dropdown. */
export async function listTemplates(): Promise<Template[]> {
  const out: Template[] = [];
  for (const [dir, source] of [
    ["templates", "template"],
    ["official", "official"],
  ] as const) {
    try {
      for (const e of await ghContents(dir)) {
        if (e.type === "dir") {
          out.push({ name: e.name, source, path: e.path });
        }
      }
    } catch {
      /* a missing folder shouldn't block the other */
    }
  }
  return out;
}

/** Recursively collect a template's files as {relative path, raw download URL}. */
async function collectFiles(repoPath: string, rel = ""): Promise<{ rel: string; url: string }[]> {
  const files: { rel: string; url: string }[] = [];
  for (const e of await ghContents(repoPath)) {
    const childRel = rel ? `${rel}/${e.name}` : e.name;
    if (e.type === "dir") {
      files.push(...(await collectFiles(e.path, childRel)));
    } else if (e.type === "file" && e.download_url) {
      files.push({ rel: childRel, url: e.download_url });
    }
  }
  return files;
}

const SKIP = new Set([".openhome.json", ".DS_Store"]);

function toClassName(name: string): string {
  return (
    name
      .split("-")
      .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
      .join("") + "Capability"
  );
}

/** Rename the template's `class XxxCapability(MatchingCapability)` to match the new name. */
async function renameCapabilityClass(mainPy: vscode.Uri, abilityName: string): Promise<void> {
  let text: string;
  try {
    text = Buffer.from(await vscode.workspace.fs.readFile(mainPy)).toString("utf8");
  } catch {
    return;
  }
  const m = text.match(/class\s+(\w+)\s*\(\s*MatchingCapability\s*\)/);
  if (!m) {
    return;
  }
  const oldClass = m[1];
  const newClass = toClassName(abilityName);
  if (oldClass === newClass) {
    return;
  }
  text = text.replace(new RegExp(`\\b${oldClass}\\b`, "g"), newClass);
  await vscode.workspace.fs.writeFile(mainPy, Buffer.from(text, "utf8"));
}

/**
 * Download a template into `destDir/<newName>` and rename its capability class.
 * Pure GitHub + filesystem — no CLI or local repo needed. Returns the new folder.
 */
export async function scaffold(
  tpl: Template,
  newName: string,
  destDir: vscode.Uri
): Promise<vscode.Uri> {
  const target = vscode.Uri.joinPath(destDir, newName);
  let exists = true;
  try {
    await vscode.workspace.fs.stat(target);
  } catch {
    exists = false;
  }
  if (exists) {
    throw new Error(`A folder named "${newName}" already exists.`);
  }

  const files = await collectFiles(tpl.path);
  if (files.length === 0) {
    throw new Error(`Template "${tpl.name}" has no files.`);
  }
  for (const f of files) {
    if (SKIP.has(f.rel.split("/").pop() || "")) {
      continue;
    }
    const resp = await fetch(f.url, { headers: { "User-Agent": "openhome-vscode" } });
    if (!resp.ok) {
      throw new Error(`Failed to download ${f.rel} (${resp.status}).`);
    }
    const bytes = new Uint8Array(await resp.arrayBuffer());
    await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(target, f.rel), bytes);
  }
  await renameCapabilityClass(vscode.Uri.joinPath(target, "main.py"), newName);
  return target;
}
