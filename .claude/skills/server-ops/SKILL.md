---
name: server-ops
description: Start, stop, restart, upgrade or inspect the Suwayomi server of this stack (scripts/start.ts, stop.ts, restart.ts, build-server.ts), including its logs and data dir. Use when the server is down or will not start, or when asked to start or restart it. Also use to upgrade Suwayomi-Server, to find where its data, config and logs live, or for access from the home network.
---

# Running the server

The server is the official Suwayomi-Server Linux release (bundled JRE, no Java needed),
installed into `server/` by `scripts/build-server.ts` from `SUWAYOMI_VERSION` in
`stack.conf`. It serves the UI, Tsumiru, from `<data>/webUI/` (`ui-patch` skill).

| Do | Run |
|---|---|
| start (background), open the UI | `scripts/start.ts` (`--no-browser`) |
| stop, verified gone | `scripts/stop.ts` |
| restart, verified new PID | `scripts/restart.ts` |
| install / upgrade the server | `scripts/build-server.ts` (`--force` reinstalls) |
| everything: UI, server, start, check | `scripts/rebuild-and-start.ts` (`--ui-only`, `--server-only`) |
| health | `tools/doctor.ts` (`stack-doctor` skill) |

These scripts start, stop and replace things the user relies on: run them when the task
asks for it, and say so. Do not run them speculatively.

## Where things are

| What | Where |
|---|---|
| data dir (`TACHIDESK_DATA`) | `~/.local/share/Tachidesk` |
| config | `<data>/server.conf` (change it through the API while running: `suwayomi-api`) |
| database | `<data>/database.mv.db` (H2). Never touch the file. Use the API |
| server log | `<data>/logs/application.log` |
| console output | `~/.local/state/manga-stack/server.out` |
| library backups | `backups/*.tachibk` in the project (daily, kept 60 days, not in git) |
| download cache | `.cache/` (release archives, checksums, the Flutter SDK) |

## Things that bite

- **One instance only.** Suwayomi guards against a second instance: a second start opens
  the web UI and quits, which looks like a successful restart. `start.ts` refuses when
  anything answers on the port, and `restart.ts` checks the PID changed.
- **`ip` applies at once** (verified 2026-11-10): the server rebinds its listener, and the
  `setSettings` request itself comes back as an HTTP 500 (`EofException`) although the setting
  took. Check with `settings { ip }` and `ss -ltn`. `webUIFlavor` and `webUIInterface` need
  `scripts/restart.ts` after `setSettings`.
- **A running server rewrites `server.conf` from memory on shutdown.** Edit the file only
  while stopped. Otherwise use `setSettings`, which persists.
- **WebView (KCEF).** `kcefEnabled = true` makes the server fetch a Chromium runtime into
  `<data>/bin/kcef` on first start. It needs X11 libraries (`libxrender`, `libxcomposite`,
  `libxdamage`, `libxkbcommon`, `libxtst`) and a `DISPLAY` (Xvfb when headless). Only some
  extensions need it. A missing library logs "Could not load 'jcef' library" and the rest
  keeps working. Check with `ldd <data>/bin/kcef/libjcef.so | grep not`.
- The tray icon and the open-browser-on-start are off (`systemTrayEnabled`,
  `initialOpenInBrowserEnabled` = false): `start.ts` opens the browser itself.
- **WSL under NAT networking** (before 2026-11-10) reached the Windows browser only because
  of `-Djava.net.preferIPv4Stack=true` in `JAVA_OPTS`: without it Java listens on an
  IPv6-mapped socket (`[::ffff:127.0.0.1]:4567` in `ss -ltn`), which NAT mode did not forward.
  Kept: harmless with mirrored networking.

## Home network

The server listens on every address (`server.ip = 0.0.0.0`), so phones on the home Wi-Fi open
`http://<PC address>:4567` (`manga-url` or `ipconfig` prints it). Done once on Windows: WSL
mirrored networking (`.wslconfig`) and the Hyper-V firewall rule `Suwayomi` (TCP 4567 from
`192.168.0.0/24`). No login, so home network only. Bubble-text boxes work on the PC only.

## Upgrading Suwayomi-Server

1. Read the release notes between the two versions (DB migrations run on first start and
   are one-way).
2. `createBackup` (`suwayomi-api`), or check that today's backup exists in `backups/`.
3. Set `SUWAYOMI_VERSION` in `stack.conf`, then `scripts/rebuild-and-start.ts --server-only`.
   `build-server.ts` verifies the download against the release's `Checksums.sha256`.
4. The server bundles its own web UI version. Check that the custom UI still loads
   (`ui-patch` -> prove it is live) and `tools/doctor.ts`.
5. Commit the `stack.conf` change.

## History

Until 2026-11-08 this ran on Windows. The library was copied from
`%LOCALAPPDATA%\Tachidesk` (database, config, extensions, source settings).
The old Windows install and web UI backups are in
`~/.local/share/manga-stack-attic/2026-11-08/` (see its `RESTORE.md`), and the old scripts
are in git history.
