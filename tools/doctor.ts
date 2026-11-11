#!/usr/bin/env bun
// Health check of the whole stack. Exits with 1 when a check FAILs. A WARN never fails.

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import {
  abs, config, DATA, expectedRevision, flags, gql, HISTORY_FILE, installedRevision, listedPatches, output, PROJECT,
  SERVED_UI, SERVER_PATH, servedRevision, READAHEAD_URL,
} from "../scripts/lib.ts";
import { cloneExists, cloneState, describeState, lintPatch, patchFilesOnDisk, REPO, seriesTree, unsaved } from "../ui/clone.ts";

const opts = flags(
  `
tools/doctor.ts             run every check
tools/doctor.ts --offline   skip the extension catalogue download

  1. skills       every project skill has a valid SKILL.md
  2. tools        bun, git, python3, unzip; the pinned Flutter SDK (needed only to build the UI)
  3. server       SERVER_DIR holds the release named by SUWAYOMI_VERSION
  4. patches      lint + the Tsumiru series applies to the TSUMIRU_VERSION tag in order
  5. clone        a known state, or edits that the next build wipes
  6. web UI       the server answers and serves the installed UI, which is the configured one
  7. config       server.conf and global meta == skills/stack-doctor/references/expected-config.md
  8. data         newest backup age; extension copies vs installed vs catalogue
  9. readahead    running; the last pass recent (passes stopped?); chapters that failed in the last day`,
  ["--offline"],
);

let fails = 0;
const ok = (msg: string) => console.log(`  ok    ${msg}`);
const warn = (msg: string) => console.log(`  WARN  ${msg}`);
const fail = (msg: string) => {
  fails++;
  console.log(`  FAIL  ${msg}`);
};
const readTrimmed = (path: string) => (existsSync(path) ? readFileSync(path, "utf8").trim() : null);
const CLAUDE_DIR = join(PROJECT, ".claude");

// ---------------------------------------------------------------- 1. skills

/** The YAML front matter of a Markdown file (between the first two --- lines). */
const frontMatter = (path: string) => readFileSync(path, "utf8").match(/^---\n(.*?)\n---\n/s)?.[1] ?? "";

function skills() {
  console.log("1. skills");
  const dir = join(CLAUDE_DIR, "skills");
  if (!existsSync(dir)) {
    warn("no .claude/skills (the Claude Code setup is not in this checkout)");
    return;
  }
  const names = readdirSync(dir).filter((d) => statSync(join(dir, d)).isDirectory()).sort();
  const bad = names.filter((n) => {
    const file = join(dir, n, "SKILL.md");
    const fm = existsSync(file) ? frontMatter(file) : "";
    return fm.match(/^name:\s*(\S+)/m)?.[1] !== n || !/^description:/m.test(fm);
  });
  if (bad.length) fail(`skills with a missing SKILL.md, or a name/description that does not match the folder: ${bad.join(", ")}`);
  else ok(`${names.length} project skills: ${names.join(", ")}`);
}

// ---------------------------------------------------------------- 2. tools, 3. server install

function tools() {
  console.log("2. tools");
  ok(`bun ${Bun.version}`);
  for (const [tool, why] of [["git", "the UI build and patch-tool"], ["python3", "readahead"], ["unzip", "the builds"]]) {
    if (Bun.which(tool)) ok(tool);
    else fail(`${tool} not on PATH (needed by ${why})`);
  }
  const flutter = join(PROJECT, ".cache", "flutter", "bin", "flutter");
  let have: string | null = null;
  try {
    have = JSON.parse(output([flutter, "--version", "--machine", "--suppress-analytics"])).frameworkVersion;
  } catch {
    // missing
  }
  if (have === config.FLUTTER_VERSION) ok(`Flutter ${have} in .cache/flutter`);
  else warn(`Flutter ${have ?? "missing"} in .cache/flutter, stack.conf wants ${config.FLUTTER_VERSION} (needed only to build the UI; scripts/build-ui.ts fetches it)`);
}

function serverInstall() {
  console.log("3. server install");
  const have = readTrimmed(join(SERVER_PATH, ".version"));
  if (!existsSync(join(SERVER_PATH, "bin", "Suwayomi-Server.jar"))) fail(`no server in ${SERVER_PATH}: scripts/build-server.ts`);
  else if (have !== config.SUWAYOMI_VERSION) {
    fail(`${SERVER_PATH} holds ${have ?? "an unknown version"}, stack.conf wants ${config.SUWAYOMI_VERSION}: scripts/build-server.ts`);
  } else ok(`server ${have} installed in ${config.SERVER_DIR}/`);
}

// ---------------------------------------------------------------- 4. patches, 5. clone

function patches() {
  console.log("4. patches");
  const listed = listedPatches();
  let clean = true;
  for (const p of [...new Set([...listed, ...patchFilesOnDisk()])]) {
    if (!existsSync(p)) {
      fail(`${basename(p)}: listed in ui/patches/series but the file is missing`);
      clean = false;
      continue;
    }
    for (const e of lintPatch(readFileSync(p, "utf8"))) {
      fail(`${basename(p)}: ${e}`);
      clean = false;
    }
  }
  const { tree, results } = seriesTree(listed);
  const failed = results.find((r) => !r.ok);
  if (failed) fail(`${basename(failed.patch)} does not apply after the ones before it (\`ui/patch-tool.ts check\` for detail)`);
  else if (clean) ok(`${listed.length} listed patches lint clean and apply in order`);
  if (tree) {
    for (const p of patchFilesOnDisk().filter((p) => !listed.includes(p))) {
      if (!seriesTree([...listed, p]).tree) warn(`${basename(p)} (unlisted) does NOT apply on top of the series`);
    }
  }
}

function clone() {
  console.log("5. clone");
  const st = cloneState();
  const text = describeState(st);
  if (st.state === "missing" || unsaved(st)) fail(text);
  else ok(text.split(". ")[0]);
}

// ---------------------------------------------------------------- 6. web UI

async function webUi(): Promise<boolean> {
  console.log("6. web UI");
  const served = await servedRevision();
  if (served === null) {
    warn(`server not answering at ${config.SUWAYOMI_URL} (server checks skipped)`);
    return false;
  }
  const installed = installedRevision();
  const expected = expectedRevision();
  if (served.startsWith("HTTP") || installed === "none") fail("up, but serves no custom UI: scripts/build-ui.ts, then scripts/restart.ts");
  else if (served !== installed) {
    fail(`serves ${served} but ${installed} is installed: the server fell back to its bundled UI (webUIFlavor not CUSTOM?) or was not restarted: scripts/restart.ts`);
  } else ok(`up, serving Tsumiru ${served}`);
  if (installed !== "none" && installed !== expected) {
    fail(`installed UI is ${installed}, stack.conf and ui/patches give ${expected}: scripts/rebuild-and-start.ts --ui-only`);
  }
  if (existsSync(SERVED_UI) && !existsSync(join(SERVED_UI, "index.html"))) fail(`${SERVED_UI}/index.html missing`);
  return true;
}

// ---------------------------------------------------------------- 7. config

/** One comparable string for a config value: comment dropped, quotes stripped, numbers as
 * numbers, lists as JSON. So `1.0`, `1` and `"1"` compare equal. */
function norm(value: string): string {
  const m = value.trim().match(/^("[^"]*"|\[[^\]]*\]|[^#]*?)\s*(#.*)?$/s);
  let v = (m ? m[1] : value).trim();
  if (v.startsWith("[")) return JSON.stringify([...v.matchAll(/"([^"]*)"/g)].map((x) => x[1]));
  v = v.replace(/^"+|"+$/g, "");
  return v !== "" && !Number.isNaN(Number(v)) ? String(Number(v)) : v;
}

/** The server.* = value lines of a server.conf. This reads a subset of HOCON: one key per line,
 * and a list can continue on the next lines until its "]". */
function confValues(path: string): Map<string, string> {
  const out = new Map<string, string>();
  const lines = readFileSync(path, "utf8").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*(server\.[A-Za-z0-9_.]+)\s*=\s*(.*)$/);
    if (!m) continue;
    let value = m[2];
    while (value.startsWith("[") && !value.includes("]") && i + 1 < lines.length) value += `\n${lines[++i]}`;
    out.set(m[1], norm(value));
  }
  return out;
}

/** key = value lines of the ```expected block in expected-config.md. */
function expectedConfig(): Map<string, string> {
  const path = join(CLAUDE_DIR, "skills", "stack-doctor", "references", "expected-config.md");
  const block = existsSync(path) ? (readFileSync(path, "utf8").match(/```expected\n(.*?)```/s)?.[1] ?? "") : "";
  const out = new Map<string, string>();
  for (const raw of block.split("\n")) {
    const line = raw.split("  #")[0].trim();
    if (!line.includes("=") || line.startsWith("#")) continue;
    const at = line.indexOf("=");
    out.set(line.slice(0, at).trim(), norm(line.slice(at + 1).trim().replaceAll("<project>", PROJECT)));
  }
  return out;
}

async function serverConfig(up: boolean) {
  console.log("7. config");
  const expected = expectedConfig();
  if (!expected.size) {
    warn("no ```expected block in .claude/skills/stack-doctor/references/expected-config.md: nothing to compare");
    return;
  }
  /** Fail on every expected key with the given prefix whose value differs. */
  const compare = (what: string, prefix: string, have: Map<string, string>) => {
    const keys = [...expected.keys()].filter((k) => k.startsWith(prefix));
    const drift = keys.filter((k) => have.get(k) !== expected.get(k));
    for (const k of drift) fail(`${what} drift: ${k} = ${have.get(k) ?? "(unset)"} (expected ${expected.get(k)})`);
    if (!drift.length) ok(`${what} matches ${keys.length} expected settings`);
  };

  const conf = join(DATA, "server.conf");
  if (existsSync(conf)) compare("server.conf", "server.", confValues(conf));
  else warn(`no server.conf at ${conf} (TACHIDESK_DATA)`);

  if (![...expected.keys()].some((k) => k.startsWith("webUI_"))) return;
  if (!up) {
    warn("global meta not checked (server down)");
    return;
  }
  try {
    const nodes: { key: string; value: string }[] = (await gql("{ metas { nodes { key value } } }")).metas.nodes;
    compare("global meta", "webUI_", new Map(nodes.map((n) => [n.key, norm(n.value)])));
  } catch (err) {
    warn(`global meta not readable: ${String(err).slice(0, 120)}`);
  }
}

// ---------------------------------------------------------------- 8. data

function data() {
  console.log("8. data");
  const dir = join(PROJECT, "backups");
  const backups = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".tachibk")).map((f) => join(dir, f)) : [];
  if (!backups.length) warn("no backups in backups/ (server.backupPath)");
  else {
    const newest = backups.reduce((a, b) => (statSync(a).mtimeMs >= statSync(b).mtimeMs ? a : b));
    const days = (Date.now() - statSync(newest).mtimeMs) / 86_400_000;
    const msg = `newest backup ${basename(newest)} is ${days.toFixed(1)} days old (${backups.length} kept)`;
    if (days > 2) warn(`${msg}: backupInterval is 1 day, is the server running and backupPath right?`);
    else ok(msg);
  }
  if (opts.has("--offline")) return;
  const r = Bun.spawnSync([process.execPath, join(PROJECT, "tools", "ext-check.ts"), "--quiet"]);
  for (const line of r.stdout.toString().split("\n").filter(Boolean)) warn(`extension ${line.trim()}`);
  if (r.exitCode === 0) ok("extension copies, server and catalogue agree");
}

// ---------------------------------------------------------------- 9. readahead

/** From the pass history file, so it works while readahead is down. */
async function readahead() {
  console.log("9. readahead");
  if (!existsSync(join(PROJECT, "readahead"))) {
    ok("not in this checkout (optional)");
    return;
  }
  if (!existsSync(abs(config.UPSCALE_MODEL))) {
    warn("not installed (scripts/build-readahead.ts)");
    return;
  }
  const interval = Number(config.READAHEAD_INTERVAL_MINUTES || 60);
  try {
    const health: any = await (await fetch(`${READAHEAD_URL}/health`, { signal: AbortSignal.timeout(3000) })).json();
    const running = health.passRunning ? " (a pass is running)" : "";
    ok(`running: ${health.model} on ${health.device}; next pass due ${health.nextPassDue}${running}`);
  } catch {
    warn("not running: scripts/readahead.ts start (or scripts/start.ts)");
  }
  const lines = existsSync(HISTORY_FILE) ? readFileSync(HISTORY_FILE, "utf8").split("\n").filter((l) => l.trim()) : [];
  if (!lines.length) {
    warn(`no passes recorded yet (${HISTORY_FILE})`);
    return;
  }
  type Pass = { started: string; result: string; failed?: string[] };
  const passes: Pass[] = lines.map((l) => JSON.parse(l));
  const started = (p: Pass) => Date.parse(p.started.replace(" ", "T")); // local time
  // Lines are written when a pass ends, so the latest start may not be on the last line.
  const last = passes.reduce((a, b) => (started(a) >= started(b) ? a : b));
  const ageMinutes = (Date.now() - started(last)) / 60_000;
  const day = passes.filter((p) => Date.now() - started(p) < 86_400_000);
  const msg = `last pass ${last.started} (${last.result}), ${day.length} in the last 24 h`;
  if (interval && ageMinutes > 2 * interval + 10) {
    warn(`${msg}: none for ${(ageMinutes / 60).toFixed(1)} h although one is due every ${interval} min`);
  } else ok(msg);
  const failed = day.flatMap((p) => p.failed ?? []);
  if (failed.length) {
    warn(`${failed.length} jobs failed in the last 24 h: ${failed.slice(0, 5).join(", ")}${failed.length > 5 ? " ..." : ""} (scripts/readahead.ts history; readahead.out)`);
  }
}

// ---------------------------------------------------------------- main

console.log(`project ${PROJECT}\nserver  ${config.SUWAYOMI_URL}\ndata    ${DATA}${existsSync(DATA) ? "" : " (missing)"}`);
skills();
tools();
serverInstall();
if (cloneExists()) {
  patches();
  clone();
} else {
  console.log("4-5. patches, clone");
  warn(`no Tsumiru clone at ${REPO} (TSUMIRU_REPO): scripts/build-ui.ts creates it`);
}
const up = await webUi();
await serverConfig(up);
data();
await readahead();
console.log(fails ? `${fails} check(s) failed.` : "All checks passed.");
process.exit(fails ? 1 : 0);
