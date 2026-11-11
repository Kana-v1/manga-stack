#!/usr/bin/env bun
// Stop the Suwayomi server started from this project, and make sure it is gone.

import { existsSync } from "node:fs";
import { join } from "node:path";
import { config, die, flags, info, PROJECT, runScript, SERVER_PATH, serverAnswers, serverPids, stopProcesses, warn } from "./lib.ts";

const opts = flags(
  `
scripts/stop.ts                 the server and readahead
scripts/stop.ts --server-only   the server only (restart.ts uses this)

Sends SIGTERM (the server shuts down cleanly) and waits up to 30 s, then SIGKILL. H2 recovers
from its transaction log after a kill, but a clean stop is better.`,
  ["--server-only"],
);

// Readahead is optional: a checkout without it has no scripts/readahead.ts.
const withReadahead = existsSync(join(PROJECT, "scripts", "readahead.ts"));
if (!opts.has("--server-only") && withReadahead) runScript("readahead.ts", ["stop"]);

const pids = serverPids();
if (!pids.length) {
  if (await serverAnswers()) {
    warn(`a server answers at ${config.SUWAYOMI_URL} but was not started from ${SERVER_PATH}; leaving it alone`);
  }
  info("not running");
  process.exit(0);
}

info(`stopping PID ${pids.join(" ")}`);
if (!(await stopProcesses(serverPids, 30))) die(`could not stop PID ${serverPids().join(" ")}`);
info("stopped");
