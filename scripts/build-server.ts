#!/usr/bin/env bun
// Install (or upgrade to) the Suwayomi-Server release in SUWAYOMI_VERSION, into SERVER_DIR.

import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { config, die, download, fileHash, flags, info, PROJECT, run, SERVER_PATH, serverPids } from "./lib.ts";

const opts = flags(
  `
scripts/build-server.ts            install if SERVER_DIR holds another version or nothing
scripts/build-server.ts --force    reinstall even when the version matches

Downloads the official linux-x64 release (bundled JRE, so no Java needed) into .cache/, checks
it against the release's Checksums.sha256, and swaps it in. The Electron runtime in the archive
is skipped: it is only used with server.webUIInterface = ELECTRON. The server must be stopped
first; data in TACHIDESK_DATA is not touched.`,
  ["--force"],
);

const version = config.SUWAYOMI_VERSION;
const versionFile = join(SERVER_PATH, ".version");
if (!opts.has("--force") && existsSync(versionFile) && readFileSync(versionFile, "utf8").trim() === version) {
  info(`server ${version} already installed in ${SERVER_PATH} (--force to reinstall)`);
  process.exit(0);
}
if (serverPids().length) die(`the server is running (PID ${serverPids().join(" ")}). Stop it first: scripts/stop.ts`);

const name = `Suwayomi-Server-${version}-linux-x64`;
const asset = `${name}.tar.gz`;
const base = `https://github.com/Suwayomi/Suwayomi-Server/releases/download/${version}`;
const cache = join(PROJECT, ".cache");
const archive = join(cache, asset);
const sums = join(cache, `Checksums-${version}.sha256`);
mkdirSync(cache, { recursive: true });

if (!existsSync(sums)) {
  info(`downloading checksums for ${version}`);
  await download(`${base}/Checksums.sha256`, sums);
}
// Lines of "<sha256>  <file name>"
const expected = readFileSync(sums, "utf8")
  .split("\n")
  .map((line) => line.trim().split(/\s+/))
  .find(([, file]) => file === asset)?.[0];
if (!expected) die(`${asset} is not listed in ${sums}`);

if (!existsSync(archive) || (await fileHash(archive)) !== expected) {
  info(`downloading ${asset} (~320 MB)`);
  await download(`${base}/${asset}`, archive);
}
info("verifying sha256");
if ((await fileHash(archive)) !== expected) die(`checksum mismatch for ${archive}; delete it and retry`);

// Unpack next to the target (same filesystem), then swap, so a failure leaves the old install.
const staging = mkdtempSync(join(PROJECT, ".server-staging."));
process.on("exit", () => rmSync(staging, { recursive: true, force: true }));
info("unpacking (without electron/)");
run(["tar", "-xzf", archive, "-C", staging, "--exclude=*/electron", "--exclude=*/electron/*"]);
const unpacked = join(staging, name);
if (!existsSync(join(unpacked, "bin", "Suwayomi-Server.jar")) || !existsSync(join(unpacked, "jre", "bin", "java"))) {
  die(`unexpected archive layout in ${asset}`);
}
writeFileSync(join(unpacked, ".version"), `${version}\n`);

if (existsSync(SERVER_PATH)) renameSync(SERVER_PATH, join(staging, "previous"));
renameSync(unpacked, SERVER_PATH);
info(`server ${version} installed in ${SERVER_PATH}`);
