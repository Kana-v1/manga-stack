#!/usr/bin/env bun
// Restart the server for real: stop, start, and check that a new process is serving.

import { die, flags, runScript, serverPids } from "./lib.ts";

const opts = flags(
  `
scripts/restart.ts [--no-browser]

Needed after installing a new web UI, or after changing a setting that is wired at startup
(webUIFlavor, webUIInterface). Readahead keeps running.`,
  ["--no-browser"],
);

const before = serverPids().join(" ");
if (runScript("stop.ts", ["--server-only"]) !== 0) process.exit(1);
if (runScript("start.ts", [...opts]) !== 0) process.exit(1);
const after = serverPids().join(" ");
if (!after) die("no server process after the restart");
if (before && after === before) die(`PID ${after} is the same as before the restart`);
