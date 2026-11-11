# The setup: map, owners, and how to change it

The map of this project and its Claude tooling. Read it instead of deducing the layout from
the files. **It is a map, not the territory:** on any conflict the owning file wins (table
below). If what you observe differs from what is written here, say so, name the file and
line, then fix the drift or this doc, and say which you did. A stale map gets trusted.

## Layout

| Path | What | In git |
|---|---|---|
| `stack.conf` | everything that varies: versions, URL, data dir, `TSUMIRU_*`, `FLUTTER_*`, `READAHEAD_*`, `UPSCALE_*`, `OCR_*` | yes |
| `scripts/` | build-server, build-ui, build-readahead, start, stop, restart, rebuild-and-start, readahead (Bun + TypeScript, each runnable as `scripts/<name>.ts`). `lib.ts` is shared by the scripts and the tools: config, paths, processes, server calls, revisions, downloads | yes |
| `tools/` | `doctor`, `gql`, `library`, `ext-check` (`tools/<name>.ts`): checks and queries | yes |
| `package.json`, `tsconfig.json`, `bun.lock` | type checking only (`bun run check`). The scripts need no packages | yes |
| `node_modules/` | TypeScript and Bun's type definitions, from `bun install` | no |
| `ui/` | our changes to the UI: `patches/*.patch` in the order of `patches/series`, `apply.ts` (apply them), `patch-tool.ts` (edit one), `clone.ts` (shared by those, the build and `doctor`), `README.md` | yes |
| `readahead/` | the readahead service (modules listed at the top of `readahead.py`), requirements, `pyproject.toml` (ruff and mypy settings) | yes |
| `readahead/.venv/`, `readahead/models/` | PyTorch CUDA venv (~5.5 GB), the model | no |
| `recommendations/` | local research notes for a future recommender (`README.md` data sources, `implicit-signals.md`, `learning-path.md`). Code for it will go here too | notes: no (git-ignored). Code: yes |
| `extensions/` | local copies of the installed extensions | yes |
| `backups/` | daily library backups the server writes (`*.tachibk`) | no (folder kept by `.gitkeep`) |
| `server/` | Suwayomi-Server release, unpacked by `build-server.ts` | no |
| `ui/Suwayomi-Tsumiru/` | upstream clone (its own git repo), at the `TSUMIRU_VERSION` tag | no |
| `.cache/` | release downloads, checksums, the Flutter SDK (`.cache/flutter`, ~2.3 GB) | no |
| `~/.local/share/Tachidesk/` | server data: `server.conf`, `database.mv.db`, `logs/`, `downloads/`, `webUI/` | no |
| `~/.local/state/manga-stack/` | server and readahead console output. Readahead's record of its downloads (`readahead-downloads.json`) and pass history (`readahead-passes.jsonl`) | no |
| Windows: `%USERPROFILE%\.wslconfig`, Hyper-V firewall rule `Suwayomi` | WSL networking mirrored. TCP 4567 open to `192.168.0.0/24` only (`server-ops`, "Home network") | no |

## Claude tooling

| Path | What |
|---|---|
| `CLAUDE.md` | rules needed in most sessions, the case -> route table, pointers |
| `.claude/skills/<name>/` | one skill per task. Project: `ui-patch`, `readahead`, `server-ops`, `suwayomi-api`, `library-progress`, `suwayomi-extensions`, `stack-doctor`. Upstream (provenance and local changes in `THIRD_PARTY.md`): `dart-run-static-analysis`, `dart-resolve-package-conflicts`, `ruff`, `graphql-operations`, `systematic-debugging`, `verification-before-completion`, `webapp-testing` |
| `.claude/settings.json` | permission allow-list for read-only tool calls (`tools/doctor.ts`, `gql`, ...). Commit/PR attribution off |

There are no project agents or hooks. The hooks built first, and the agents and skills of
the removed Suwayomi-WebUI setup, are in git history.

## Ownership

On conflict, these win over this doc and over skills that paraphrase them.

| File | Owns |
|---|---|
| `stack.conf` | versions, paths, URL, the patch order, model and PyTorch pins |
| `scripts/build-ui.ts` | how Tsumiru is cloned and built, and its revision string |
| `scripts/build-server.ts` | how the server release is downloaded, checked and installed |
| `scripts/start.ts`, `stop.ts`, `restart.ts`, `readahead.ts` | process handling (processes found by their command line), readiness checks |
| `readahead/*.py` | what a pass does (`background.py`), what it picks (`planner.py`), what it may delete (`owned.py`, `cleanup.py`), page handling (`pages.py`), the download-folder naming (`suwayomi.py`) |
| `ui/patches/suwayomi-tsumiru-reader-html-images.patch` | the `<img>` rendering of reader pages |
| `ui/patches/suwayomi-tsumiru-upscaled-mark.patch` | the "HD" mark on upscaled chapters in the chapter list |
| `ui/patches/suwayomi-tsumiru-bubble-text.patch`, `...-click-scroll-stops.patch` | the bubble boxes, and where a forward click stops |
| `.claude/skills/stack-doctor/references/expected-config.md` | the intended server settings |
| `ui/clone.ts` `lintPatch()` | the patch lint rules |

## Contracts nothing tests

The seams where drift is silent. Check both sides when touching either.

| Contract | Sides | Breaks as |
|---|---|---|
| config precedence (file, then env) and syntax | `scripts/lib.ts loadConfig()` <-> `readahead/config.py read_conf()` | the scripts and tools disagree with readahead about paths or URL |
| the state dir `~/.local/state/manga-stack` | `scripts/lib.ts STATE_DIR` <-> `readahead/config.py STATE_DIR` | readahead's record and history are not where the scripts and `doctor` look |
| the pass history line (`started`, `result`, `failed`) | `readahead/history.py` <-> `tools/doctor.ts readahead()` and `scripts/readahead.ts history` | `doctor` misreads or ignores stalled and failing passes |
| revision `TSUMIRU_VERSION+<sha256 of the patches, 8 chars>` | `scripts/lib.ts expectedRevision()` (one place) <-> the `revision` file in `<data>/webUI` that `build-ui.ts` wrote | `doctor` reports a pending build forever, or never |
| unsaved clone edits stop a reset | `ui/clone.ts unsaved()` <-> `applySeries()` (`ui/apply.ts`, `build-ui.ts`) and `patch-tool.ts workon/reset`, which reset the clone | edits that are in no patch get wiped |
| download folder naming | server `SafePath.buildValidFilename` <-> `readahead/suwayomi.py safe_name` | jobs fail with "download folder not found" after a server upgrade |
| the record of readahead's downloads | `owned.add` before every download it starts (`jobs.py`) <-> `cleanup.py`, which deletes only recorded downloads | a download it made is never cleaned up (not recorded), or one it did not make is deleted (recorded wrongly) |
| readahead's port 8765 | `READAHEAD_PORT` in `stack.conf` <-> `_readaheadPort` in the bubble-text patch | the reader shows no bubble boxes |
| the text file of a chapter (`/api/ocr`): `pages[].index`, `regions[].box` (fractions), `pages[].panels` (fractions) | `readahead/ocr.py read_chapter` and `ads.py shift` <-> `bubble_text_layer.dart _fetch` | no bubble boxes, or clicks that stop in the wrong place |
| the tag key `manga_stack_upscaled` | `readahead/tags.py KEY` <-> `isUpscaled` in the upscaled-mark patch | the "HD" mark never shows |
| when a library update is done | the server stamps `lastUpdateTimestamp` at the start of an update <-> `suwayomi.py update_library` | a pass plans before the update ran, or waits 10 minutes and fails |
| the `expected` code block format | `expected-config.md` <-> `doctor.ts expectedConfig()` | doctor checks nothing and passes |
| skill names | `CLAUDE.md` routes <-> `.claude/skills/` | a route to a skill that does not exist |
| GraphQL shapes in `suwayomi-api/references/recipes.md` | recipes <-> server schema of `SUWAYOMI_VERSION` | recipes fail after a server upgrade. Re-check with `gql --type` |
| UI <-> server version pairing | `TSUMIRU_VERSION` <-> `SUWAYOMI_VERSION` (Tsumiru's mapping file) | the UI misbehaves in ways that look like bugs |

## Changing the setup

- **Where a rule lives**, by how reliably it must hold:
  - checkable and must never break -> a script or tool refuses (the build refuses to wipe
    unsaved edits, `gql` refuses a mutation without `--mutate`).
  - needed in most sessions and short -> `CLAUDE.md`.
  - needed for one kind of task -> that task's skill.
  - a map or cross-cutting reference -> this doc.
- When the user has to repeat a text rule, the rule moves up a level: into a script or tool
  check.
- A new check must catch a real past mistake: run it on that case and show that it fires,
  and that it stays quiet on a correct case.
- After changing a tool or script: `tools/doctor.ts`, and run the changed command once
  for real.
- Third-party skills: re-copy from upstream and re-apply the change listed in
  `.claude/skills/THIRD_PARTY.md`.
