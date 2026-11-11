#!/usr/bin/env bun
// Start the Suwayomi server, which serves the custom web UI, and wait until it answers.

import { existsSync } from "node:fs";
import { join } from "node:path";
import {
  alive, config, DATA, DEFAULT_DATA, die, flags, info, installedRevision, runScript,
  SERVED_UI, SERVER_JAR, SERVER_LOG, SERVER_PATH, serverAnswers, serverPids, servedRevision,
  startDetached, readaheadInstalled, warn,
} from "./lib.ts";

const opts = flags(
  `
scripts/start.ts                start in the background, then open the UI in a browser
scripts/start.ts --no-browser   do not open a browser

Also starts readahead when it is installed (scripts/readahead.ts). Console output goes to
~/.local/state/manga-stack/server.out; the server's own log is <data>/logs/application.log.
If it is already running, this only says where.`,
  ["--no-browser"],
);

const url = config.SUWAYOMI_URL;

function openUi() {
  if (opts.has("--no-browser")) return;
  const desktop = process.env.DISPLAY || process.env.WAYLAND_DISPLAY;
  const opener = desktop && Bun.which("xdg-open") ? "xdg-open" : Bun.which("wslview") ? "wslview" : null;
  if (opener) Bun.spawn([opener, url], { stdout: "ignore", stderr: "ignore" }).unref();
  else info(`open ${url} in a browser`);
}

if (readaheadInstalled() && runScript("readahead.ts", ["start"]) !== 0) {
  warn("readahead did not start: chapters download without upscaling");
}

const running = serverPids();
if (running.length) {
  info(`already running (PID ${running.join(" ")}), serving web UI ${(await servedRevision()) ?? "none"} at ${url}`);
  openUi();
  process.exit(0);
}
if (await serverAnswers()) die(`something else already answers at ${url}; not starting a second server`);
if (!existsSync(SERVER_JAR)) die(`no server in ${SERVER_PATH}: run scripts/build-server.ts`);
if (!existsSync(join(SERVED_UI, "revision"))) {
  warn(`no custom web UI in ${SERVED_UI}, so the server serves its bundled one. Run scripts/build-ui.ts`);
}

const jvm = config.JAVA_OPTS.split(/\s+/).filter(Boolean);
if (DATA !== DEFAULT_DATA) jvm.push(`-Dsuwayomi.tachidesk.config.server.rootDir=${DATA}`);
const cmd = [join(SERVER_PATH, "jre", "bin", "java"), ...jvm, "-jar", SERVER_JAR];
// Like the release's own launcher: run from SERVER_PATH, with its crash-handler library preloaded.
const pid = startDetached(cmd, {
  cwd: SERVER_PATH,
  env: { LD_PRELOAD: join(SERVER_PATH, "bin", "catch_abort.so") },
  log: SERVER_LOG,
});
info(`starting (PID ${pid}), waiting for ${url}`);

let up = false;
for (let i = 0; i < 180 && !up; i++) {
  if (!alive(pid)) {
    const tail = (await Bun.file(SERVER_LOG).text()).split("\n").slice(-31).join("\n");
    console.error(tail);
    die(`the server exited during startup (full output: ${SERVER_LOG})`);
  }
  up = await serverAnswers();
  if (!up) await Bun.sleep(1000);
}
if (!up) die(`no answer after 180 s (PID ${pid} still running; see ${SERVER_LOG} and ${DATA}/logs/application.log)`);

const rev = (await servedRevision()) ?? "none";
info(`serving ${url} (PID ${pid}, web UI ${rev})`);
if (rev !== installedRevision()) {
  warn(`the installed UI is ${installedRevision()}: the server fell back to its bundled UI, or webUIFlavor is not CUSTOM`);
}
openUi();
