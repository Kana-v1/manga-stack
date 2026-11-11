# manga-stack

Self-hosted manga reader, replacing reading on demonicscans.org. Suwayomi-Server (official
Linux release) serves Suwayomi-Tsumiru (Flutter web app) built from source with local
patches, plus readahead: an hourly service that prepares the next unread chapters (download,
OCR, ad cuts, 2x GPU upscale).
All MPL-2.0. Owning the code so it can be changed is the point. Everything that varies
(versions, URL, paths, the patch list, the model) is in `stack.conf`.

Situational detail lives in skills (`.claude/skills/`, routed below). The map of the whole
setup, and how to change it: `.claude/agent_docs/harness.md`.

## Commands

```bash
scripts/start.ts | stop.ts | restart.ts                   # server + readahead; the server serves the UI
scripts/build-ui.ts                                       # Tsumiru + ui/patches -> <data>/webUI
scripts/build-server.ts                                   # server release -> server/
scripts/build-readahead.ts                                # readahead venv (PyTorch CUDA) + model
scripts/readahead.ts status | plan | pass | history       # readahead's passes
scripts/rebuild-and-start.ts [--ui-only]                  # rebuild, start, check the new UI is live
tools/doctor.ts                                           # health of everything, readahead too
tools/gql.ts | library.ts | ext-check.ts                 # server queries, library, extensions
ui/patch-tool.ts | ui/apply.ts                            # UI patches: edit one, apply all (ui/README.md)
```

## Hard rules

- **A UI change exists only as a `ui/patches/*.patch` listed in `ui/patches/series`.** Never
  edit `<data>/webUI/`. Edit the `ui/Suwayomi-Tsumiru/` clone only inside `patch-tool workon` /
  `export`: the build resets it. (`ui-patch`)
- **Change server state through the API**, never `database.mv.db`, and `server.conf` only
  while the server is stopped (a running server rewrites it on shutdown). Mutations change
  the user's library with no undo: say what changes first. `createBackup` before bulk
  changes. (`suwayomi-api`, `library-progress`)
- **A deploy is done when `/revision` equals the build**, not when the script exits. The
  server silently falls back to its bundled UI. (`ui-patch`, `verification-before-completion`)
- **The UI's version must match the server's** (Tsumiru's `versionToServerVersionMapping.json`).
  A WebUI ahead of its server made the old UI flash its splash screen every few seconds.
- **Latest chapter is `highestNumberedChapter.chapterNumber`**, never `chapters.totalCount`.
  Marking chapters read needs `lastPageRead` too, or `lastReadAt` stays empty. (`library-progress`)
- **The extension catalogue is `index.pb`** (gzip, no Content-Encoding), never
  `index.min.json` (a 2-entry stub). (`suwayomi-extensions`)
- Run scripts that start, stop or replace things only when the task asks for it.
- Commit or push only when the user asks.

## Case -> route

| Case | Route |
|---|---|
| Change reader/library behaviour, a patch fails to apply, the Flutter build fails, upgrade Tsumiru | `ui-patch` (+ `dart-run-static-analysis`, `dart-resolve-package-conflicts`) |
| The UI looks wrong, blurry or stale | `ui-patch` -> When the UI looks wrong, + `systematic-debugging` |
| Upscaled chapters, the hourly pass, the "HD" mark, the model | `readahead` (+ `ruff`). Its Python must pass strict `mypy`, with no `Any` |
| Start, stop, restart or upgrade the server. Its logs and data dir | `server-ops` |
| Settings, metadata, any query or mutation | `suwayomi-api`, `graphql-operations` |
| Library, reading progress, chapter numbers, syncing progress | `library-progress` |
| Extensions, sources, the catalogue | `suwayomi-extensions` |
| "Is everything OK?", after a build, restart or upgrade | `stack-doctor` |
| About to say something works or is fixed | `verification-before-completion` |
| Browser automation, screenshots | `webapp-testing` (ask first: the user prefers to check the browser themselves) |

## Environment

- Linux (WSL2, mirrored networking) at `~/Projects/manga-stack`. The server also answers on
  the home network, without a login (`server-ops`, "Home network").
- Data dir `~/.local/share/Tachidesk`. The library (35 titles, migrated from DemonicScans via
  the same-source Manga Demon extension) came from the old Windows install on 2026-11-08.
- GPU: RTX 3070 Ti (8 GB) visible in WSL. PyTorch CUDA in `readahead/.venv`.
- The scripts and tools run on Bun (`~/.bun/bin`). A non-interactive shell may need
  `export PATH=$HOME/.bun/bin:$PATH`. `bun run check` type-checks them after a change.
- Building the UI needs the pinned Flutter SDK (`.cache/flutter`, fetched by `build-ui.ts`).
  The server needs no Java (bundled JRE).
- History: the Windows scripts and the removed Suwayomi-WebUI setup are in git history
  (tag `before-tsumiru` marks the last WebUI-only state).
