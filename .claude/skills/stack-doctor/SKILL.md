---
name: stack-doctor
description: Check the health of the whole manga stack and fix what it finds. It checks the server, the served web UI revision, the patch series and clone state, config drift, backups, extension versions and readahead's hourly passes. Use when asked whether everything is OK, after a deploy, restart or migration, or when something "stopped working" and the cause is not yet known.
---

# Stack health check

```bash
tools/doctor.ts             # exit 1 if any FAIL; WARN never fails
tools/doctor.ts --offline   # skip the extension catalogue download
```

Report FAILs first, each with its fix. Do not "fix" a WARN the user may have chosen (an old
Flutter SDK when nothing needs building, an unlisted patch).

## What a finding means

| Finding | Cause | Fix |
|---|---|---|
| serves X but Y is installed | the server fell back to its bundled UI, or was not restarted | check `webUIFlavor = CUSTOM`, `scripts/restart.ts` (`ui-patch`) |
| installed UI is X, stack.conf and ui/patches give Y | a patch or the version changed since the last build | `scripts/rebuild-and-start.ts --ui-only` |
| server not installed / other version | `server/` missing or `SUWAYOMI_VERSION` changed | `scripts/build-server.ts` (`server-ops`) |
| serves no custom UI | `<data>/webUI` is empty or was built without `build-ui.ts` | `scripts/build-ui.ts`, restart |
| patch does not apply | the Tsumiru version moved, or a patch was edited | `ui-patch` -> Upgrading Tsumiru |
| clone DIRTY / unexported | edits in no patch. The next deploy wipes them | `ui/patch-tool.ts status --diff`, then `export` or `salvage` |
| server.conf drift | changed in the UI or by hand | set it back with `setSettings` (`suwayomi-api`), or update the expected value if the change was deliberate |
| global meta drift | a reader setting changed in the UI | same: set it back, or update the expected value |
| newest backup > 2 days old | server down, or `backupPath` wrong | check `backupPath`. A Linux server needs the Linux path |
| extension update available / local copy older | catalogue moved on | `suwayomi-extensions` |
| server not answering | not running, or on another port | `scripts/start.ts`. Check `SUWAYOMI_URL` (`server-ops`) |
| Flutter missing or another version | `.cache/flutter` absent or `FLUTTER_VERSION` changed | harmless until a build: `scripts/build-ui.ts` fetches it |
| readahead not running | stopped, or failed at start | `scripts/readahead.ts start`. The reason is at the end of `readahead.out` (`readahead`) |
| no pass for over twice the interval | readahead was down, or a pass hangs (one runs until its last chapter is done) | `scripts/readahead.ts status` and `history`, then `readahead.out` |
| jobs failed in the last 24 h | a download, upscale or text read failed for a chapter | `scripts/readahead.ts history`. The error is in `readahead.out` (`readahead`) |

## Expected configuration

`references/expected-config.md` holds the intended `server.conf` values and web UI settings,
with the reason for each. `doctor` reads its `expected` block, so that file is the single
list: when a setting changes on purpose, change it there.
