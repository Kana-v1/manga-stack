// Shared by the scripts (scripts/) and tools (tools/): config, paths, output, processes, HTTP
// and the server's GraphQL API, the web UI revision, downloads. Imported, not run.

import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, cpSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

export const PROJECT = resolve(import.meta.dir, "..");

// ---------------------------------------------------------------- config

/** Expands ~, $VAR, ${VAR} and ${VAR:-default} the way a shell would (no other syntax). */
function expand(value: string): string {
  const expanded = value.replace(
    /\$\{(\w+)(?::-([^}]*))?\}|\$(\w+)/g,
    (_, braced: string | undefined, fallback: string | undefined, bare: string | undefined) =>
      process.env[braced ?? bare ?? ""] || (fallback !== undefined ? expand(fallback) : ""),
  );
  return expanded.startsWith("~/") ? join(homedir(), expanded.slice(2)) : expanded;
}

/** The settings in stack.conf: KEY="value" lines in shell syntax. A quoted value can continue
 * on the next lines. Outside quotes, # starts a comment. An environment variable with the same
 * name has priority. readahead/config.py reads the file in the same way. */
function loadConfig(): Record<string, string> {
  const text = readFileSync(join(PROJECT, "stack.conf"), "utf8");
  const config: Record<string, string> = {};
  // KEY="value" (may span lines), KEY='value', or KEY=value up to a # or the end of the line
  for (const [, key, ...values] of text.matchAll(/^\s*([A-Z_][A-Z0-9_]*)=(?:"([^"]*)"|'([^']*)'|([^#\n]*))/gm)) {
    const value = values.find((v) => v !== undefined)!.trim();
    config[key] = expand(process.env[key] ?? value);
  }
  return config;
}

export const config = loadConfig();

// ---------------------------------------------------------------- paths

/** A path from stack.conf: relative ones are relative to the project. */
export const abs = (path: string) => (isAbsolute(path) ? path : join(PROJECT, path));

export const SERVER_PATH = abs(config.SERVER_DIR);
export const SERVER_JAR = join(SERVER_PATH, "bin", "Suwayomi-Server.jar");
export const DATA = config.TACHIDESK_DATA;
export const SERVED_UI = join(DATA, "webUI"); // what the server serves (webUIFlavor = CUSTOM)
export const DEFAULT_DATA = join(process.env.XDG_DATA_HOME || join(homedir(), ".local", "share"), "Tachidesk");
// Console output and the state of readahead. readahead/config.py uses the same folder.
export const STATE_DIR = join(process.env.XDG_STATE_HOME || join(homedir(), ".local", "state"), "manga-stack");
export const SERVER_LOG = join(STATE_DIR, "server.out");
export const READAHEAD_DIR = join(PROJECT, "readahead");
export const READAHEAD_PY = join(READAHEAD_DIR, ".venv", "bin", "python");
export const READAHEAD_LOG = join(STATE_DIR, "readahead.out");
export const READAHEAD_URL = `http://127.0.0.1:${config.READAHEAD_PORT}`;
export const HISTORY_FILE = join(STATE_DIR, "readahead-passes.jsonl"); // one line per pass (readahead/history.py)

// ---------------------------------------------------------------- output and arguments

export const info = (msg: string) => console.log(`\x1b[36m==\x1b[0m ${msg}`);
export const warn = (msg: string) => console.error(`\x1b[33mWARN\x1b[0m ${msg}`);

export function die(msg: string): never {
  console.error(`\x1b[31mERROR\x1b[0m ${msg}`);
  process.exit(1);
}

/** The flags of the script from the command line. Each flag must be one of `known`. -h or
 * --help prints the usage and exits. */
export function flags(usage: string, known: string[]): Set<string> {
  const given = new Set(process.argv.slice(2));
  if (given.has("-h") || given.has("--help")) {
    console.log(usage.trim());
    process.exit(0);
  }
  for (const flag of given) if (!known.includes(flag)) die(`unknown option ${flag}`);
  return given;
}

// ---------------------------------------------------------------- processes

type RunOptions = { cwd?: string; env?: Record<string, string | undefined>; check?: boolean };

/** Run a command, with its output in this terminal. Returns the exit code. When the command
 * fails, stops the script, unless check is false. */
export function run(cmd: string[], { cwd, env, check = true }: RunOptions = {}): number {
  const r = spawnSync(cmd[0], cmd.slice(1), { cwd, env: { ...process.env, ...env }, stdio: "inherit" });
  const code = r.status ?? 1;
  if (check && code !== 0) die(`failed (exit ${code}): ${cmd.join(" ")}`);
  return code;
}

/** The standard output of a command, trimmed. "" when the command fails or does not exist. */
export function output(cmd: string[], { cwd }: { cwd?: string } = {}): string {
  const r = spawnSync(cmd[0], cmd.slice(1), { cwd, encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
}

/** Run another script of this folder, with the same Bun. Returns its exit code. */
export function runScript(name: string, args: string[] = []): number {
  return run([process.execPath, join(PROJECT, "scripts", name), ...args], { check: false });
}

export function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** PIDs of the processes whose command line contains `pattern`. */
const pidsOf = (pattern: string) => output(["pgrep", "-f", "--", pattern]).split("\n").filter(Boolean).map(Number);

/** The server started from this project's SERVER_DIR, by any means. */
export const serverPids = () => pidsOf(`-jar ${SERVER_JAR}`);
export const readaheadPids = () => pidsOf(join(READAHEAD_DIR, "readahead.py"));

/** Local time as "2026-11-10 09:59:55", the format of the logs and the pass history. */
export const timestamp = (date = new Date()) => date.toLocaleString("sv-SE");

/** Start a command in the background, detached from this script. Its output goes to the end of
 * `log`, after a "=== start <time> ===" line. Returns the PID. The process continues to run
 * when the script exits. */
export function startDetached(cmd: string[], { cwd, env, log }: { cwd?: string; env?: Record<string, string>; log: string }): number {
  mkdirSync(STATE_DIR, { recursive: true });
  appendFileSync(log, `\n=== start ${timestamp()} ===\n`);
  const fd = openSync(log, "a");
  const child = spawn(cmd[0], cmd.slice(1), {
    cwd,
    env: { ...process.env, ...env },
    detached: true,
    stdio: ["ignore", fd, fd],
  });
  child.unref();
  if (!child.pid) die(`could not start ${cmd[0]}`);
  return child.pid;
}

/** Send SIGTERM, then wait up to `seconds` for the processes to stop. Send SIGKILL to the
 * processes that still run. True when no process is left. */
export async function stopProcesses(pids: () => number[], seconds: number): Promise<boolean> {
  const signal = (sig: NodeJS.Signals) => {
    for (const pid of pids()) {
      try {
        process.kill(pid, sig);
      } catch {
        // already gone
      }
    }
  };
  signal("SIGTERM");
  for (let i = 0; i < seconds * 2 && pids().length; i++) await Bun.sleep(500);
  if (pids().length) {
    warn(`still running after ${seconds} s; killing it`);
    signal("SIGKILL");
    await Bun.sleep(1000);
  }
  return pids().length === 0;
}

// ---------------------------------------------------------------- HTTP and the server

/** True when something answers at the URL (any HTTP status). */
export async function answers(url: string, seconds = 2): Promise<boolean> {
  try {
    await fetch(url, { signal: AbortSignal.timeout(seconds * 1000) });
    return true;
  } catch {
    return false;
  }
}

export const serverAnswers = () => answers(`${config.SUWAYOMI_URL}/`);

export async function readaheadAnswers(): Promise<boolean> {
  try {
    const r = await fetch(`${READAHEAD_URL}/health`, { signal: AbortSignal.timeout(2000) });
    return r.ok;
  } catch {
    return false;
  }
}

export const readaheadInstalled = () => existsSync(READAHEAD_PY) && existsSync(abs(config.UPSCALE_MODEL));

/** The server does not answer. */
export class ServerDown extends Error {}

/** An answer with GraphQL errors. The message is the message of the first error. `errors` has
 * all of them. */
export class GqlError extends Error {
  constructor(public errors: { message?: string }[]) {
    const first = errors[0]?.message ?? "GraphQL error";
    super(errors.length > 1 ? `${first} (and ${errors.length - 1} more)` : first);
  }
}

/** Run a GraphQL query or mutation on the server. Returns its `data`. */
export async function gql<T = any>(query: string, variables: object = {}, seconds = 30): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.SUWAYOMI_URL}/api/graphql`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
      signal: AbortSignal.timeout(seconds * 1000),
    });
  } catch (err) {
    throw new ServerDown(`not answering at ${config.SUWAYOMI_URL}: ${err}`);
  }
  const text = await response.text();
  let out: { data?: T; errors?: { message?: string }[] };
  try {
    out = JSON.parse(text);
  } catch {
    throw new GqlError([{ message: `HTTP ${response.status}: ${text.slice(0, 300)}` }]);
  }
  if (out.errors?.length) throw new GqlError(out.errors);
  return out.data as T;
}

// ---------------------------------------------------------------- the web UI

/** Our changes to the UI: patch files, applied in the order ui/patches/series lists them. */
export const PATCH_DIR = join(PROJECT, "ui", "patches");

/** The patch files in ui/patches/series, in order, as absolute paths. The file names one
 * patch per line. # starts a comment. */
export function listedPatches(): string[] {
  const series = join(PATCH_DIR, "series");
  if (!existsSync(series)) return [];
  return readFileSync(series, "utf8")
    .split("\n")
    .map((line) => line.split("#")[0].trim())
    .filter(Boolean)
    .map((name) => join(PATCH_DIR, name));
}

/** The revision of the web UI that the server serves. null when the server does not answer.
 * "HTTP <status>" when it answers without a revision (no custom web UI). */
export async function servedRevision(): Promise<string | null> {
  try {
    const r = await fetch(`${config.SUWAYOMI_URL}/revision`, { signal: AbortSignal.timeout(2000) });
    return r.ok ? (await r.text()).trim() : `HTTP ${r.status}`;
  } catch {
    return null;
  }
}

/** The revision of the UI installed for the server to serve, or "none". */
export function installedRevision(): string {
  const path = join(SERVED_UI, "revision");
  return existsSync(path) ? readFileSync(path, "utf8").trim() : "none";
}

/** The revision of a build of the configured Tsumiru: the version, "+", and 8 hex digits. The
 * digits are the start of a sha256 over the patch files in order. A change to a patch gives a
 * new revision. */
export function expectedRevision(): string {
  const hash = new Bun.CryptoHasher("sha256");
  for (const p of listedPatches()) hash.update(readFileSync(p));
  return `${config.TSUMIRU_VERSION}+${hash.digest("hex").slice(0, 8)}`;
}

/** Install a built UI folder as the served one, keeping the previous one as webUI.prev. */
export function installUi(src: string) {
  if (!existsSync(join(src, "index.html")) || !existsSync(join(src, "revision"))) {
    die(`no UI build in ${src} (index.html + revision)`);
  }
  mkdirSync(DATA, { recursive: true });
  if (existsSync(SERVED_UI)) {
    rmSync(`${SERVED_UI}.prev`, { recursive: true, force: true });
    renameSync(SERVED_UI, `${SERVED_UI}.prev`);
  }
  cpSync(src, SERVED_UI, { recursive: true, preserveTimestamps: true });
  console.log(`  installed Tsumiru ${installedRevision()} into ${SERVED_UI} (previous one kept in webUI.prev)`);
}

// ---------------------------------------------------------------- downloads and checksums

/** Download a URL to a file (through `<file>.part`, so a broken download leaves no file), with
 * up to 3 tries. Shows the progress of big ones. */
export async function download(url: string, path: string) {
  for (let attempt = 1; ; attempt++) {
    try {
      const r = await fetch(url);
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
      const total = Number(r.headers.get("content-length")) || 0;
      const big = total > 50e6;
      const out = Bun.file(`${path}.part`).writer();
      let got = 0;
      let shown = 0;
      for await (const chunk of r.body) {
        out.write(chunk);
        got += chunk.length;
        if (big && got - shown >= total / 50) {
          shown = got;
          process.stderr.write(`\r  ${Math.round((got / total) * 100)}% of ${Math.round(total / 1e6)} MB`);
        }
      }
      await out.end();
      if (big) process.stderr.write("\n");
      renameSync(`${path}.part`, path);
      return;
    } catch (err) {
      if (attempt === 3) die(`download failed: ${url}: ${err}`);
      warn(`download failed (${err}); trying again`);
      await Bun.sleep(3000);
    }
  }
}

/** sha256 hex digest of a file, read in chunks (some are a GB). */
export async function fileHash(path: string): Promise<string> {
  const hash = new Bun.CryptoHasher("sha256");
  for await (const chunk of Bun.file(path).stream()) hash.update(chunk);
  return hash.digest("hex");
}
