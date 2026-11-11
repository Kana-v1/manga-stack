#!/usr/bin/env bun
// Rebuild everything and start: the server release, the UI (Tsumiru), then the server,
// checking that the new UI is what is served.

import { die, flags, info, installedRevision, runScript, servedRevision } from "./lib.ts";

const opts = flags(
  `
scripts/rebuild-and-start.ts                 server (only if SUWAYOMI_VERSION changed) + UI
scripts/rebuild-and-start.ts --ui-only       skip the server step
scripts/rebuild-and-start.ts --server-only   skip the UI step
scripts/rebuild-and-start.ts --force         reinstall the server even if the version matches
scripts/rebuild-and-start.ts --no-browser    do not open a browser at the end

The UI is built while the old server keeps running, so a failed build stops nothing.`,
  ["--ui-only", "--server-only", "--force", "--no-browser"],
);
const ui = !opts.has("--server-only");
const server = !opts.has("--ui-only");

/** Run a script of this folder. Stop here when it fails. */
const step = (name: string, args: string[] = []) => runScript(name, args) === 0 || process.exit(1);

if (ui) step("build-ui.ts");
step("stop.ts");
if (server) step("build-server.ts", opts.has("--force") ? ["--force"] : []);
step("start.ts", opts.has("--no-browser") ? ["--no-browser"] : []);

if (ui) {
  const served = (await servedRevision()) ?? "none";
  const built = installedRevision();
  if (served !== built) die(`the server serves ${served}, not the new build ${built}`);
  info(`Tsumiru ${built} is live`);
}
