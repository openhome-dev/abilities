import * as vscode from "vscode";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

const DEFAULT_BASE = "https://app.openhome.com";
const SECRET_API_KEY = "openhome.apiKey";
const SECRET_JWT = "openhome.jwt";

/** Thrown when no credential is available for an action; callers show a login CTA. */
export class NotAuthenticatedError extends Error {}
/** Thrown when a JWT session has expired. */
export class SessionExpiredError extends Error {}

export interface Agent {
  id: string;
  name: string;
  description?: string;
}

export interface Ability {
  id: string;
  name: string;
  category?: string;
  description?: string;
  triggerWords: string[];
  isInstalled: boolean;
  isPublished: boolean;
}

interface InstalledAbility {
  id: string;
  name: string;
  category?: string;
  triggerWords: string[];
  enabled: boolean;
  systemCapability: boolean;
  agentCapability: boolean;
}

interface Creds {
  apiKey?: string;
  jwt?: string;
  apiBase: string;
}

type AuthMode = "apikey_body" | "xapikey" | "jwt";

let secrets: vscode.SecretStorage | undefined;

export function initApi(storage: vscode.SecretStorage): void {
  secrets = storage;
}

export async function storeCredentials(apiKey: string, jwt?: string): Promise<void> {
  await secrets?.store(SECRET_API_KEY, apiKey);
  if (jwt) {
    await secrets?.store(SECRET_JWT, jwt);
  }
}

export async function clearCredentials(): Promise<void> {
  await secrets?.delete(SECRET_API_KEY);
  await secrets?.delete(SECRET_JWT);
}

/** Normalize a pasted token: strip quotes/whitespace and a leading "Bearer ". */
function cleanToken(value: string | undefined | null): string | undefined {
  if (!value) {
    return undefined;
  }
  let v = value.trim().replace(/^["']|["']$/g, "").trim();
  if (v.slice(0, 7).toLowerCase() === "bearer ") {
    v = v.slice(7).trim();
  }
  return v || undefined;
}

function readConfigFile(): Record<string, any> {
  try {
    const raw = fs.readFileSync(path.join(os.homedir(), ".openhome", "config.json"), "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

/** Read OPENHOME_* keys from a .env at the workspace root (best-effort fallback). */
function readDotenv(): Record<string, string> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!root) {
    return {};
  }
  try {
    const text = fs.readFileSync(path.join(root, ".env"), "utf8");
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const t = line.trim().replace(/^export\s+/, "");
      if (!t || t.startsWith("#") || !t.includes("=")) {
        continue;
      }
      const idx = t.indexOf("=");
      const key = t.slice(0, idx).trim();
      const val = t.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
      if (key.startsWith("OPENHOME_")) {
        out[key] = val;
      }
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * Resolve credentials, mirroring the CLI's priority order:
 * SecretStorage (this extension) → real env vars → workspace .env → ~/.openhome/config.json.
 */
async function getCreds(): Promise<Creds> {
  const file = readConfigFile();
  const env = readDotenv();
  const apiKey = cleanToken(
    (await secrets?.get(SECRET_API_KEY)) ||
      process.env.OPENHOME_API_KEY ||
      env.OPENHOME_API_KEY ||
      file.api_key
  );
  const jwt = cleanToken(
    (await secrets?.get(SECRET_JWT)) ||
      process.env.OPENHOME_JWT ||
      env.OPENHOME_JWT ||
      file.jwt
  );
  const apiBase = (
    process.env.OPENHOME_API_BASE ||
    env.OPENHOME_API_BASE ||
    file.api_base ||
    DEFAULT_BASE
  ).replace(/\/+$/, "");
  return { apiKey, jwt, apiBase };
}

/** True when any credential is available (used to decide login vs. data views). */
export async function isConfigured(): Promise<boolean> {
  const c = await getCreds();
  return Boolean(c.apiKey || c.jwt);
}

/**
 * Environment variables to inject when launching the CLI, so it uses the same
 * credentials the extension is signed in with (the CLI can't read our
 * SecretStorage). Only includes what's set.
 */
export async function cliEnv(): Promise<Record<string, string>> {
  const c = await getCreds();
  const env: Record<string, string> = {};
  if (c.apiKey) {
    env.OPENHOME_API_KEY = c.apiKey;
  }
  if (c.jwt) {
    env.OPENHOME_JWT = c.jwt;
  }
  if (c.apiBase && c.apiBase !== DEFAULT_BASE) {
    env.OPENHOME_API_BASE = c.apiBase;
  }
  return env;
}

const RETRYABLE = new Set([429, 500, 502, 503, 504]);

function authHeaders(auth: AuthMode, creds: Creds): Record<string, string> {
  if (auth === "xapikey") {
    if (!creds.apiKey) {
      throw new NotAuthenticatedError("This action needs an API key.");
    }
    return { "X-API-KEY": creds.apiKey };
  }
  if (auth === "jwt") {
    if (creds.jwt) {
      return { Authorization: `Bearer ${creds.jwt}` };
    }
    if (creds.apiKey) {
      return { "X-API-KEY": creds.apiKey };
    }
    throw new NotAuthenticatedError("This action needs an API key (or a JWT).");
  }
  return {}; // apikey_body — credential travels in the JSON body
}

async function request(
  method: string,
  pathname: string,
  opts: { auth?: AuthMode; json?: any; creds?: Creds } = {}
): Promise<any> {
  const creds = opts.creds ?? (await getCreds());
  const auth = opts.auth ?? "apikey_body";
  const headers = authHeaders(auth, creds);
  let body: string | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const usedJwt = auth === "jwt" && Boolean(creds.jwt);
  const url = `${creds.apiBase}${pathname}`;

  let lastErr: Error | undefined;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt) {
      await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** attempt, 8000)));
    }
    let resp: Response;
    try {
      resp = await fetch(url, { method, headers, body });
    } catch (e) {
      lastErr = new Error(`Network error contacting ${creds.apiBase}: ${String(e)}`);
      continue;
    }
    if (RETRYABLE.has(resp.status)) {
      lastErr = new Error(`Server error ${resp.status}`);
      continue;
    }
    if (!resp.ok) {
      await raiseForResponse(resp, usedJwt);
    }
    const text = await resp.text();
    if (!text) {
      return {};
    }
    try {
      return JSON.parse(text);
    } catch {
      return { raw: text };
    }
  }
  throw lastErr ?? new Error(`Request to ${pathname} failed`);
}

async function raiseForResponse(resp: Response, usedJwt: boolean): Promise<never> {
  let message = resp.statusText;
  try {
    const body: any = JSON.parse(await resp.text());
    message = body?.detail || body?.error?.message || message;
  } catch {
    /* non-JSON error body */
  }
  const lowered = (message || "").toLowerCase();
  const expiredHints = ["token not valid", "token is invalid", "not valid for any token"];
  if (usedJwt && (resp.status === 401 || expiredHints.some((h) => lowered.includes(h)))) {
    throw new SessionExpiredError("Your session token (JWT) has expired.");
  }
  throw new Error(message || `Request failed (${resp.status})`);
}

// ── public operations ──────────────────────────────────────────────────────

/** Verify a specific API key (used during login, before it's stored). */
export async function verifyApiKey(apiKey: string, jwt?: string): Promise<boolean> {
  const creds = await getCreds();
  const result = await request("POST", "/api/sdk/verify_apikey", {
    auth: "apikey_body",
    json: { api_key: apiKey },
    creds: { ...creds, apiKey, jwt: jwt ?? creds.jwt },
  });
  if (result && typeof result === "object" && "valid" in result) {
    return Boolean(result.valid);
  }
  return true;
}

export async function listAgents(): Promise<Agent[]> {
  const creds = await getCreds();
  const result = await request("POST", "/api/sdk/get_personalities", {
    auth: "apikey_body",
    json: { api_key: creds.apiKey, with_image: true },
    creds,
  });
  const rows: any[] = Array.isArray(result?.personalities) ? result.personalities : [];
  return rows.map((r) => ({ id: String(r.id), name: r.name ?? "", description: r.description }));
}

export async function listAbilities(): Promise<Ability[]> {
  const result = await request("GET", "/api/capabilities/get-all-capabilities/", { auth: "jwt" });
  const rows: any[] = Array.isArray(result) ? result : result?.abilities ?? [];
  return rows.map((r) => ({
    id: String(r.id),
    name: r.name ?? "",
    category: r.category,
    description: r.description,
    triggerWords: Array.isArray(r.trigger_words) ? r.trigger_words : [],
    isInstalled: Boolean(r.is_installed),
    isPublished: Boolean(r.is_published),
  }));
}

async function listInstalled(): Promise<InstalledAbility[]> {
  const result = await request("GET", "/api/capabilities/get-installed-capabilities/", { auth: "jwt" });
  const rows: any[] = Array.isArray(result) ? result : result?.capabilities ?? [];
  return rows.map((r) => ({
    id: String(r.id),
    name: r.name ?? "",
    category: r.category,
    triggerWords: Array.isArray(r.trigger_words) ? r.trigger_words : [],
    enabled: Boolean(r.enabled),
    systemCapability: Boolean(r.system_capability),
    agentCapability: Boolean(r.agent_capability),
  }));
}

/** Resolve an installed ability by installed id, name, or capability id. */
async function findInstalled(idOrName: string): Promise<InstalledAbility> {
  const installed = await listInstalled();
  for (const ia of installed) {
    if (ia.id === idOrName || ia.name === idOrName) {
      return ia;
    }
  }
  // Bridge capability id → name → installed record.
  const abilities = await listAbilities();
  const match = abilities.find((a) => a.id === idOrName || a.name === idOrName);
  if (match) {
    const byName = installed.find((ia) => ia.name === match.name);
    if (byName) {
      return byName;
    }
    throw new Error(`"${match.name}" is on your account but not installed, so it can't be edited.`);
  }
  throw new Error(`Ability "${idOrName}" not found.`);
}

/** PUT the full installed-capability object (the API replaces, not patches). */
async function editInstalled(
  ia: InstalledAbility,
  changes: { enabled?: boolean; triggerWords?: string[] }
): Promise<void> {
  await request("PUT", `/api/capabilities/edit-installed-capability/${ia.id}/`, {
    auth: "xapikey",
    json: {
      enabled: changes.enabled ?? ia.enabled,
      name: ia.name,
      category: ia.category || "skill",
      trigger_words: changes.triggerWords ?? ia.triggerWords,
      system_capability: ia.systemCapability,
      agent_capability: ia.agentCapability,
    },
  });
}

export async function setEnabled(idOrName: string, enabled: boolean): Promise<void> {
  const ia = await findInstalled(idOrName);
  await editInstalled(ia, { enabled });
}

export async function setTriggers(idOrName: string, triggerWords: string[]): Promise<void> {
  const ia = await findInstalled(idOrName);
  await editInstalled(ia, { triggerWords });
}

export async function deleteAbility(idOrName: string): Promise<void> {
  const abilities = await listAbilities();
  const match = abilities.find((a) => a.id === idOrName || a.name === idOrName);
  if (!match) {
    throw new Error(`Ability "${idOrName}" not found on this account.`);
  }
  await request("POST", "/api/capabilities/delete-capability/", {
    auth: "jwt",
    json: { capability_ids: [Number(match.id)] },
  });
}
