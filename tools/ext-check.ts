#!/usr/bin/env bun
// Compare the versions of the extensions: the local copies in extensions/, the versions installed
// on the server, and the catalogue.
//
// The catalogue is index.pb (EXTENSION_INDEX). This script unpacks it, because the file is gzip
// WITHOUT a Content-Encoding header, so fetch does not unpack it. index.min.json is an old stub
// with 2 entries: do not use it. The local copies are important because a third party keeps the
// catalogue. If the catalogue goes away, the local copies stay.

import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { config, flags, gql, PROJECT } from "../scripts/lib.ts";

const opts = flags(
  `
tools/ext-check.ts           table of every extension seen in any of the three
tools/ext-check.ts --quiet   only lines that need action (exit 1 if any)`,
  ["--quiet"],
);
const quiet = opts.has("--quiet");

// tachiyomi-en.mangademon-v1.4.12.apk -> language, name, version
const FILE = /tachiyomi-([a-z-]+)\.([a-z0-9]+)-v([0-9.]+)\.(apk|jar)/g;

/** "1.4.12" -> [1, 4, 12], compared number by number. */
const parts = (v: string) => (v.match(/\d+/g) ?? ["0"]).map(Number);
function newer(a: string, b: string): boolean {
  const [x, y] = [parts(a), parts(b)];
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] ?? -1) !== (y[i] ?? -1)) return (x[i] ?? -1) > (y[i] ?? -1);
  }
  return false;
}

/** "lang.name" -> the newest version among the file names in `text`. */
function newest(text: string, fileRe = FILE): Map<string, string> {
  const out = new Map<string, string>();
  for (const [, lang, name, version] of text.matchAll(fileRe)) {
    const key = `${lang}.${name}`;
    if (!out.has(key) || newer(version, out.get(key)!)) out.set(key, version);
  }
  return out;
}

const extDir = join(PROJECT, "extensions");
const local = newest(existsSync(extDir) ? readdirSync(extDir).join("\n") : "");

let catalogue: Map<string, string> | null = null;
try {
  const r = await fetch(config.EXTENSION_INDEX, { signal: AbortSignal.timeout(20_000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  let raw = new Uint8Array(await r.arrayBuffer());
  if (raw[0] === 0x1f && raw[1] === 0x8b) raw = Bun.gunzipSync(raw); // gzip magic bytes
  // A protobuf: binary, with the APK file names in it as plain text.
  catalogue = newest(Buffer.from(raw).toString("latin1"), /tachiyomi-([a-z-]+)\.([a-z0-9]+)-v([0-9.]+)\.(apk)/g);
  if (catalogue.size < 10) console.error(`catalogue lists only ${catalogue.size} extensions: is EXTENSION_INDEX the stub?`);
} catch (err) {
  console.error(`catalogue not reachable (${err}); comparing local and server only`);
}

let server: Map<string, string> | null = new Map();
try {
  const data = await gql("{ extensions(condition: {isInstalled: true}) { nodes { pkgName versionName hasUpdate } } }", {}, 10);
  for (const n of data.extensions.nodes) {
    const m = n.pkgName.match(/\.extension\.([a-z-]+)\.([a-z0-9]+)$/);
    if (m) server.set(`${m[1]}.${m[2]}`, n.versionName);
  }
} catch (err) {
  server = null;
  console.error(`server not answering (${String(err).slice(0, 80)}); comparing local and catalogue only`);
}

const keys = [...new Set([...local.keys(), ...(server?.keys() ?? [])])].sort();
let needAction = 0;
if (!quiet) console.log(`${"extension".padEnd(22)} ${"local copy".padStart(10)} ${"installed".padStart(10)} ${"catalogue".padStart(10)}  note`);
for (const key of keys) {
  const lv = local.get(key);
  const sv = server?.get(key);
  const cv = catalogue?.get(key);
  const notes: string[] = [];
  if (cv && sv && newer(cv, sv)) notes.push("update available in the catalogue");
  if (sv && (!lv || newer(sv, lv))) notes.push("local copy older than installed: copy the new one into extensions/");
  if (server && lv && !sv) notes.push("not installed on the server");
  if (catalogue && !cv) notes.push("GONE from the catalogue: keep the local copy");
  if (notes.length) needAction++;
  if (notes.length || !quiet) {
    console.log(`${key.padEnd(22)} ${(lv ?? "-").padStart(10)} ${(sv ?? "-").padStart(10)} ${(cv ?? "-").padStart(10)}  ${notes.join("; ")}`);
  }
}
process.exit(quiet && needAction ? 1 : 0);
