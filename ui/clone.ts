// The Tsumiru clone and the patch series. The series is the patches in ui/patches, in the order
// of ui/patches/series. They apply onto the TSUMIRU_VERSION tag in the TSUMIRU_REPO clone.
// ui/apply.ts, ui/patch-tool.ts, scripts/build-ui.ts and tools/doctor.ts use this file. Import
// it: do not run it.
//
// The method that this file uses everywhere: GIT_INDEX_FILE points git at a private index. Then
// git can apply patches and hash a whole folder into a "tree". This does not touch the files,
// commits or real index of the clone. Two trees with the same hash have the same content. So a
// comparison of hashes tells which known state the clone is in.

import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { abs, config, die, info, listedPatches, PATCH_DIR, PROJECT, run } from "../scripts/lib.ts";

export const REPO = resolve(abs(config.TSUMIRU_REPO));
/** The upstream tag the patches target: TSUMIRU_VERSION, or HEAD when unset. */
export const BASE_REF = config.TSUMIRU_VERSION || "HEAD";

// ---------------------------------------------------------------- git

type GitResult = { ok: boolean; stdout: string; stderr: string };

/** Run git in the clone. Throws when it fails, unless check is false. */
export function git(args: string[], { env = {}, check = true }: { env?: Record<string, string>; check?: boolean } = {}): GitResult {
  const r = Bun.spawnSync(["git", "-C", REPO, "-c", "core.autocrlf=false", ...args], {
    env: { ...process.env, ...env },
  });
  const result = { ok: r.exitCode === 0, stdout: r.stdout.toString(), stderr: r.stderr.toString().trim() };
  if (check && !result.ok) throw new Error(`git ${args.join(" ")}: ${result.stderr || result.stdout.trim()}`);
  return result;
}

/** A diff between two trees, as a patch file holds it. */
export const diff = (from: string, to: string) =>
  git(["diff", "--binary", "--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/", from, to]).stdout;

export const cloneExists = () => existsSync(join(REPO, ".git"));

const gitDir = () => git(["rev-parse", "--absolute-git-dir"]).stdout.trim();

/** The tree of the TSUMIRU_VERSION tag. */
export const baseTree = () => git(["rev-parse", `${BASE_REF}^{tree}`]).stdout.trim();

/** Every *.patch in patches/, sorted. */
export function patchFilesOnDisk(): string[] {
  if (!existsSync(PATCH_DIR)) return [];
  return readdirSync(PATCH_DIR).filter((f) => f.endsWith(".patch")).sort().map((f) => join(PATCH_DIR, f));
}

// ---------------------------------------------------------------- trees

export type ApplyResult = { patch: string; ok: boolean; error: string };

/** Apply patches in order onto the TSUMIRU_VERSION tag, in a temporary index. Returns the tree
 * that results (null when a patch fails) and the result of each patch. Stops at the first
 * failure: later patches may need it, so their results would mean nothing. This only adds
 * objects to the object store of the clone. Its files and real index do not change. */
export function seriesTree(patches: string[]): { tree: string | null; results: ApplyResult[] } {
  const tmp = mkdtempSync(join(tmpdir(), "manga-stack-series-"));
  try {
    const env = { GIT_INDEX_FILE: join(tmp, "index") };
    git(["read-tree", BASE_REF], { env });
    const results: ApplyResult[] = [];
    for (const patch of patches) {
      const r = existsSync(patch) ? git(["apply", "--cached", patch], { env, check: false }) : null;
      results.push({ patch, ok: !!r?.ok, error: r ? r.stderr : "file not found" });
      if (!r?.ok) return { tree: null, results };
    }
    return { tree: git(["write-tree"], { env }).stdout.trim(), results };
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

/** The tree of the clone's working folder as it is now (tracked and untracked files, without
 * git-ignored ones). Keeps its private index in .git, so git's file-stat cache makes repeat
 * calls fast. */
export function worktreeTree(): string {
  const env = { GIT_INDEX_FILE: join(gitDir(), "harness-index") };
  if (!existsSync(env.GIT_INDEX_FILE)) git(["read-tree", "HEAD"], { env });
  git(["add", "-A"], { env });
  return git(["write-tree"], { env }).stdout.trim();
}

// ---------------------------------------------------------------- workon: editing one patch

/** Written by `patch-tool workon`: the patch being edited and the trees to diff against. */
export type Workon = { patch: string; base_tree: string; start_tree: string; exported_tree: string };

const workonFile = () => join(gitDir(), "harness-workon.json");

export function readWorkon(): Workon | null {
  try {
    return JSON.parse(readFileSync(workonFile(), "utf8"));
  } catch {
    return null;
  }
}

export const saveWorkon = (work: Workon) => writeFileSync(workonFile(), JSON.stringify(work));
export const clearWorkon = () => rmSync(workonFile(), { force: true });

// ---------------------------------------------------------------- the clone's state

/**
 * pristine  the clone is the TSUMIRU_VERSION tag
 * deployed  the tag + every listed patch (what scripts/build-ui.ts leaves)
 * workon    `patch-tool workon` is active. `exported` tells whether the edits are saved.
 * dirty     none of these: edits that are in no patch, which the next build deletes
 * staleWorkon: a workon marker that stays from before the last build or reset
 */
export type CloneState =
  | { state: "missing" }
  | { state: "pristine" | "deployed"; tree: string; staleWorkon: boolean }
  | { state: "workon"; tree: string; patch: string; exported: boolean }
  | { state: "dirty"; tree: string };

export function cloneState(): CloneState {
  if (!cloneExists()) return { state: "missing" };
  const tree = worktreeTree();
  const work = readWorkon();
  if (work && (tree === work.exported_tree || tree === work.start_tree)) {
    return { state: "workon", tree, patch: work.patch, exported: true };
  }
  if (tree === baseTree()) return { state: "pristine", tree, staleWorkon: !!work };
  const listed = listedPatches();
  if (listed.length && seriesTree(listed).tree === tree) {
    // a build after a workon resets the clone: the workon marker is then stale
    return { state: "deployed", tree, staleWorkon: !!work };
  }
  if (work) return { state: "workon", tree, patch: work.patch, exported: false };
  return { state: "dirty", tree };
}

/** The clone holds edits that are in no patch file (yet). */
export const unsaved = (st: CloneState) => st.state === "dirty" || (st.state === "workon" && !st.exported);

export function describeState(st: CloneState): string {
  switch (st.state) {
    case "missing":
      return `no git clone at ${REPO}`;
    case "pristine":
      return "pristine (the TSUMIRU_VERSION tag, no patches applied)";
    case "deployed":
      return `deployed state: the TSUMIRU_VERSION tag + all ${listedPatches().length} listed patches. \`git diff\` here ` +
        "bundles every patch together; use `ui/patch-tool.ts workon <name>.patch` before editing";
    case "workon":
      return `workon ${basename(st.patch)} (${st.exported ? "edits exported" : "UNEXPORTED edits"}; ` +
        "`ui/patch-tool.ts export` saves them)";
    case "dirty":
      return "DIRTY: edits that are in no patch file. The next build resets the clone and wipes them " +
        "(`ui/patch-tool.ts status --diff` shows them)";
  }
}

/** Back to the TSUMIRU_VERSION tag exactly, the way scripts/build-ui.ts resets it. Not
 * `clean -x`: generated code, .dart_tool/ and build/ are git-ignored and stay, which keeps the
 * next build fast. */
export function resetClone() {
  git(["reset", "-q"]); // unstage everything, so checkout restores every file
  git(["checkout", "--", "."]);
  git(["clean", "-fdq"]);
  if (!git(["rev-parse", "-q", "--verify", `${BASE_REF}^{commit}`], { check: false }).ok) {
    git(["fetch", "-q", "--tags", "origin"]);
  }
  git(["checkout", "-q", "--detach", BASE_REF]);
  clearWorkon();
}

/** The clone at the TSUMIRU_VERSION tag with every patch of the series applied, cloned first
 * when it is missing: what scripts/build-ui.ts builds. Stops (dies) over edits in the clone
 * that are in no patch file, which the reset would wipe, unless `force`. */
export function applySeries({ force = false }: { force?: boolean } = {}) {
  if (!cloneExists()) {
    info(`cloning ${config.TSUMIRU_URL}`);
    run(["git", "-c", "core.autocrlf=false", "clone", config.TSUMIRU_URL, REPO]);
  }
  git(["config", "core.autocrlf", "false"]); // patches are LF; a checkout with CRLF would not take them
  const st = cloneState();
  if (!force && unsaved(st)) {
    die(`the Tsumiru clone is ${describeState(st)}, and resetting it would wipe the edits.
  See them: ui/patch-tool.ts status --diff     (save: patch-tool.ts export / salvage)
  Discard them: run again with --force`);
  }
  info(`resetting ${config.TSUMIRU_REPO} to ${BASE_REF}`);
  resetClone();
  for (const patch of listedPatches()) {
    console.log(`  applying ${patch.slice(PROJECT.length + 1)}`);
    const r = git(["apply", "--whitespace=nowarn", patch], { check: false });
    if (!r.ok) die(`${patch} does not apply to Tsumiru ${BASE_REF}\n${r.stderr}`);
  }
}

// ---------------------------------------------------------------- patch files

/** The files a patch changes. */
export function pathsTouched(text: string): string[] {
  return [...new Set([...text.matchAll(/^diff --git a\/(\S+) b\/(\S+)/gm)].map((m) => m[2]))].sort();
}

/** The problems in the text of a patch file. Empty when there is no problem. */
export function lintPatch(text: string): string[] {
  const errors: string[] = [];
  if (text.includes("\r\n")) {
    errors.push("CRLF line endings. Patches must be LF: the clone is checked out with core.autocrlf=false, so a CRLF patch does not apply.");
  }
  if (!/^diff --git /m.test(text)) errors.push("not a git diff (no `diff --git` header).");
  return errors;
}
