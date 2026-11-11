# manga-stack

A self-hosted manga reader for Linux. [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server)
serves [Suwayomi-Tsumiru](https://github.com/Suwayomi/Suwayomi-Tsumiru), which is built from
source with the changes in [`ui/patches`](ui/README.md).

## Requirements

Linux x86_64, [Bun](https://bun.sh), `git` and `unzip`. The server release brings its own Java,
and the UI build downloads its own Flutter SDK (about 2.3 GB).

## Run

```bash
scripts/build-server.ts   # download the Suwayomi-Server release that stack.conf names
scripts/build-ui.ts       # build the patched UI and install it for the server
scripts/start.ts          # start the server, then open http://127.0.0.1:4567
```

The first time only: stop the server (`scripts/stop.ts`), set
`server.webUIFlavor = "CUSTOM"` in `~/.local/share/Tachidesk/server.conf`, and start it again.
Without this, the server shows its own built-in UI.

`scripts/stop.ts` and `scripts/restart.ts` stop and restart the server. Every script has
`--help`.
