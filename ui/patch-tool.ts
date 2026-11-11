#!/usr/bin/env bun
// Work on the Tsumiru patch series safely. The series is the patches in ui/patches, applied in
// the order of ui/patches/series onto the TSUMIRU_VERSION tag in the TSUMIRU_REPO clone.
//
// Why: after a build, every listed patch is applied, so `git diff` in the clone shows them all
// together. The reset of the build (checkout + clean -fd) deletes edits that are in no patch.
// workon and export compare with the correct base. workon, salvage and reset refuse to run over
// unsaved edits, unless --force. This tool does not touch the commits, branches or real index of
// the clone.

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { abs, listedPatches } from "../scripts/lib.ts";
import {
  BASE_REF, cloneExists, cloneState, type CloneState, describeState, diff, git, lintPatch, pathsTouched, patchFilesOnDisk,
  readWorkon, REPO, resetClone, saveWorkon, seriesTree, unsaved, worktreeTree,
} from "./clone.ts";

const USAGE = `
ui/patch-tool.ts check            every listed patch applies, in order, to the TSUMIRU_VERSION tag;
                                     lint every ui/patches/*.patch (unlisted ones on top)
ui/patch-tool.ts lint FILE...     lint rules only
ui/patch-tool.ts status [--diff]  which state the clone is in; --diff shows unsaved edits;
                                     --exit-code exits 3 when there are unsaved edits
ui/patch-tool.ts workon NAME      set the clone up to edit ONE patch: reset, apply the patches before
                                     it, then the patch itself (a new NAME starts on top of the series).
                                     --3way merges a patch that stopped applying (after an upstream update)
ui/patch-tool.ts export           write the clone's edits back into the patch being worked on
ui/patch-tool.ts salvage NEW      save edits that are in no patch as a new patch on top of the series
ui/patch-tool.ts reset [--force]  clone back to the TSUMIRU_VERSION tag`;

const read = (path: string) => readFileSync(path, "utf8");
const error = (msg: string) => {
  console.error(msg);
  return 1;
};

function refuseIfUnsaved(st: CloneState, force: boolean, action: string): boolean {
  if (!unsaved(st) || force) return false;
  error(`refused to ${action}: the clone is ${describeState(st)}.
Save the edits first (\`patch-tool.ts export\` in a workon, \`patch-tool.ts salvage NEW.patch\` otherwise), or pass --force to throw them away.`);
  return true;
}

/** NAME, relative to the project. A file name alone means ui/patches/NAME. Never in the clone,
 * because the reset would delete it there. */
function targetPath(name: string): string {
  const path = resolve(abs(name.includes("/") ? name : join("ui", "patches", name)));
  if (!path.endsWith(".patch") || path.startsWith(`${REPO}/`)) {
    console.error(`patch must be a *.patch file outside the clone, got ${name}`);
    process.exit(1);
  }
  return path;
}

function lintOne(path: string, label = ""): boolean {
  const errors = lintPatch(read(path));
  for (const e of errors) console.log(`  FAIL  ${basename(path)}: ${e}`);
  if (!errors.length) console.log(`  ok    ${basename(path)} lint${label}`);
  return !errors.length;
}

function check(): number {
  const listed = listedPatches();
  let ok = true;
  console.log("lint:");
  for (const p of [...new Set([...listed, ...patchFilesOnDisk()])].sort()) {
    if (!existsSync(p)) {
      console.log(`  FAIL  ${basename(p)}: listed in ui/patches/series but the file is missing`);
      ok = false;
    } else {
      ok = lintOne(p, listed.includes(p) ? "" : " (unlisted)") && ok;
    }
  }
  console.log(`series onto ${BASE_REF}:`);
  const { tree, results } = seriesTree(listed);
  results.forEach((r, i) => console.log(`  ${r.ok ? "ok   " : "FAIL "} ${i + 1}. ${basename(r.patch)}${r.ok ? "" : `\n${r.error}`}`));
  listed.slice(results.length).forEach((p, i) => {
    console.log(`  --    ${results.length + i + 1}. ${basename(p)} (not checked: an earlier patch failed)`);
  });
  if (tree) {
    for (const p of patchFilesOnDisk().filter((p) => !listed.includes(p))) {
      const applies = !!seriesTree([...listed, p]).tree;
      console.log(`  ${applies ? "info " : "WARN "} ${basename(p)} (unlisted) ${applies ? "applies" : "does NOT apply"} on top of the series`);
    }
  }
  return ok && tree ? 0 : 1;
}

function status(showDiff: boolean, exitCode: boolean): number {
  const st = cloneState();
  console.log(describeState(st));
  if ("staleWorkon" in st && st.staleWorkon) {
    console.log("(a workon marker is left over from before the last build/reset; `patch-tool.ts reset` clears it)");
  }
  if (showDiff && unsaved(st) && st.state !== "missing") {
    // The edits since the last export, or since the deployed series.
    const work = readWorkon();
    const base = st.state === "workon" && work ? work.exported_tree || work.start_tree : seriesTree(listedPatches()).tree;
    if (!base) return error("cannot diff: the listed series does not apply");
    process.stdout.write(diff(base, st.tree));
  }
  return exitCode && unsaved(st) ? 3 : 0;
}

function workon(name: string, force: boolean, threeWay: boolean): number {
  const listed = listedPatches();
  const target = targetPath(name);
  if (refuseIfUnsaved(cloneState(), force, "reset the clone")) return 1;
  resetClone();
  // The patches before this one (all of them for a new patch) are its base.
  const before = listed.includes(target) ? listed.slice(0, listed.indexOf(target)) : listed;
  for (const p of before) {
    const r = git(["apply", p], { check: false });
    if (!r.ok) {
      resetClone();
      return error(`base patch ${basename(p)} does not apply; clone reset to pristine.\n${r.stderr}`);
    }
  }
  const baseTree = worktreeTree();
  const exists = existsSync(target);
  let conflicts: string[] = [];
  if (exists) {
    const r = git(["apply", target], { check: false });
    if (!r.ok && threeWay) {
      // --3way also stages the changes. Unstage them at once, so that `checkout -- .` of the build
      // still resets them.
      const r3 = git(["apply", "--3way", target], { check: false });
      git(["reset", "-q"]);
      conflicts = pathsTouched(read(target)).filter((f) => existsSync(join(REPO, f)) && read(join(REPO, f)).includes("<<<<<<< "));
      if (!r3.ok && !conflicts.length) {
        resetClone();
        return error(`3-way apply failed too; clone reset to pristine.\n${r3.stderr}`);
      }
    } else if (!r.ok) {
      resetClone();
      return error(`${basename(target)} does not apply on its base (${before.length} patches before it); clone reset to pristine. Retry with --3way to merge it and resolve conflicts by hand.\n${r.stderr}`);
    }
  }
  const startTree = worktreeTree();
  saveWorkon({ patch: target, base_tree: baseTree, start_tree: startTree, exported_tree: startTree });
  console.log(`workon ${basename(target)}: clone = ${BASE_REF} + ${before.length} patch(es) before it${exists ? " + its current version" : " (new patch)"}.
Edit files in ${REPO}, then run \`ui/patch-tool.ts export\`.`);
  if (conflicts.length) {
    console.log(`3-way merge left conflict markers in:\n  ${conflicts.join("\n  ")}\nResolve them, then export. Until exported, the clone counts as unsaved.`);
  }
  if (!listed.includes(target)) console.log("Not in ui/patches/series yet: add its file name there (order matters) once it is ready.");
  return 0;
}

function exportPatch(): number {
  // The workon marker alone is not enough. A build after a workon leaves the marker (stale).
  // An export then would write every later patch into this one.
  const st = cloneState();
  const work = readWorkon();
  if (st.state !== "workon" || !work) {
    return error(`no workon active (the clone is ${describeState(st)}): run \`patch-tool.ts workon NAME.patch\` first ` +
      "(edits made without one: `patch-tool.ts salvage NEW.patch`)");
  }
  const tree = st.tree;
  if (tree === work.base_tree) return error("no changes against the base: the patch would be empty. Nothing written.");
  const text = diff(work.base_tree, tree);
  writeFileSync(work.patch, text);
  saveWorkon({ ...work, exported_tree: tree });
  const files = pathsTouched(text);
  console.log(`wrote ${work.patch} (${files.length} file(s): ${files.join(", ")})`);
  return check();
}

function salvage(name: string, force: boolean): number {
  const target = targetPath(name);
  const st = cloneState();
  if (st.state !== "dirty") return error(`nothing to salvage: the clone is ${describeState(st)}`);
  if (existsSync(target) && !force) return error(`${target} exists; pick a new name or pass --force`);
  const base = seriesTree(listedPatches()).tree;
  if (!base) return error("the listed series does not apply, so there is no base to diff against");
  const text = diff(base, st.tree);
  writeFileSync(target, text);
  console.log(`wrote ${target}: the edits on top of the deployed series (${pathsTouched(text).join(", ")}).
Review it: fold it into the patch it belongs to, or add it to ui/patches/series.`);
  return 0;
}

function main(): number {
  const { values: opts, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      diff: { type: "boolean" },
      "exit-code": { type: "boolean" },
      force: { type: "boolean" },
      "3way": { type: "boolean" },
      help: { type: "boolean", short: "h" },
    },
  });
  const [command, ...args] = positionals;
  if (opts.help || !command) {
    console.log(USAGE.trim());
    return command ? 0 : 2;
  }
  if (command === "lint") return args.map((f) => lintOne(f)).every(Boolean) ? 0 : 1;
  if (!cloneExists()) return error(`no git clone at ${REPO} (TSUMIRU_REPO; scripts/build-ui.ts creates it)`);
  const force = !!opts.force;
  switch (command) {
    case "check": return check();
    case "status": return status(!!opts.diff, !!opts["exit-code"]);
    case "workon": return args[0] ? workon(args[0], force, !!opts["3way"]) : error("usage: patch-tool.ts workon NAME.patch");
    case "export": return exportPatch();
    case "salvage": return args[0] ? salvage(args[0], force) : error("usage: patch-tool.ts salvage NEW.patch");
    case "reset":
      if (refuseIfUnsaved(cloneState(), force, "reset")) return 1;
      resetClone();
      console.log("clone reset to pristine");
      return 0;
    default:
      return error(`unknown command ${command}\n${USAGE.trim()}`);
  }
}

process.exit(main());
