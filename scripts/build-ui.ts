#!/usr/bin/env bun
// Build the UI, Suwayomi-Tsumiru (TSUMIRU_VERSION) with our patches (ui/), and install it as
// the server's web UI (<data>/webUI, the previous one kept as webUI.prev). Restart the server
// afterwards.

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { applySeries, REPO } from "../ui/clone.ts";
import {
  config, die, download, expectedRevision, fileHash, flags, info, installedRevision, installUi, output, PROJECT,
  run, serverPids,
} from "./lib.ts";

const opts = flags(
  `
scripts/build-ui.ts           build if the installed UI is not the configured one
scripts/build-ui.ts --force   build again, even over clone edits that are in no patch

Fetches the pinned Flutter SDK into .cache/flutter (sha256 checked), then does what
ui/apply.ts does (clone, reset to the TSUMIRU_VERSION tag, apply ui/patches in the order of
ui/patches/series), then pub get, gen-l10n, build_runner, flutter build web. The build's
revision is "<version>+<hash of the patches>".`,
  ["--force"],
);
const force = opts.has("--force");

const revision = expectedRevision();
if (!force && installedRevision() === revision) {
  info(`Tsumiru ${revision} is already installed (--force to build again)`);
  process.exit(0);
}

/** The pinned Flutter SDK in .cache/flutter, fetched when missing or another version. Returns
 * its bin folder. */
async function flutterSdk(): Promise<string> {
  const cache = join(PROJECT, ".cache");
  const sdk = join(cache, "flutter");
  const flutter = join(sdk, "bin", "flutter");
  let current = "";
  try {
    current = JSON.parse(output([flutter, "--version", "--machine"])).frameworkVersion;
  } catch {
    // not installed
  }
  if (current !== config.FLUTTER_VERSION) {
    const name = `flutter_linux_${config.FLUTTER_VERSION}-stable.tar.xz`;
    const tar = join(cache, name);
    info(`fetching Flutter ${config.FLUTTER_VERSION} (~1 GB)`);
    mkdirSync(cache, { recursive: true });
    if (!existsSync(tar)) {
      await download(`https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/${name}`, tar);
    }
    if ((await fileHash(tar)) !== config.FLUTTER_SHA256) die(`Flutter sha256 mismatch; delete ${tar} and retry`);
    rmSync(sdk, { recursive: true, force: true });
    run(["tar", "-xJf", tar, "-C", cache]);
    run([flutter, "config", "--no-analytics"]);
    run([flutter, "precache", "--web", "--no-android", "--no-ios", "--no-linux", "--no-windows", "--no-macos"]);
  }
  return join(sdk, "bin");
}

const flutterBin = await flutterSdk();
applySeries({ force });

info("pub get, code generation, flutter build web");
const env = { PATH: `${flutterBin}:${process.env.PATH}` }; // build_runner runs dart itself
const flutter = join(flutterBin, "flutter");
for (const cmd of [
  [flutter, "pub", "get", "--suppress-analytics"],
  [flutter, "gen-l10n", "--suppress-analytics"],
  [join(flutterBin, "dart"), "run", "build_runner", "build"],
  [flutter, "build", "web", "--release", "--suppress-analytics"],
]) {
  if (run(cmd, { cwd: REPO, env, check: false }) !== 0) die("the Tsumiru build failed");
}

// build/ is git-ignored and rewritten by every build, so the revision file can go right in.
const built = join(REPO, "build", "web");
writeFileSync(join(built, "revision"), `${revision}\n`);
installUi(built);
if (serverPids().length) info(`done. The server is running: scripts/restart.ts to serve ${revision}`);
else info("done. Start the server: scripts/start.ts");
