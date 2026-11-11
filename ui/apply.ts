#!/usr/bin/env bun
// Apply our changes to the UI:
// 1. Clone Suwayomi-Tsumiru into TSUMIRU_REPO, if the clone is missing.
// 2. Reset the clone to the TSUMIRU_VERSION tag.
// 3. Apply the patches in ui/patches, in the order of ui/patches/series.
// The result is the patched source, ready to build. scripts/build-ui.ts does the same step
// before it builds. Use this script to look at or work on the patched source without a build.

import { flags, info } from "../scripts/lib.ts";
import { applySeries, REPO } from "./clone.ts";

const opts = flags(
  `
ui/apply.ts           reset the clone and apply every patch
ui/apply.ts --force   also over edits in the clone that are in no patch file (they are lost)`,
  ["--force"],
);

applySeries({ force: opts.has("--force") });
info(`done: ${REPO} is the TSUMIRU_VERSION tag with every patch applied`);
