---
name: suwayomi-extensions
description: Install, update or check Suwayomi extensions (the sources, e.g. Manga Demon and MangaDex) and the keiyoushi extension catalogue. Use when a source stops working, an extension needs an update, an extension install or update fails (504), or the catalogue shows almost no extensions.
---

# Extensions and the catalogue

## In use

| Extension | Package suffix | Why |
|---|---|---|
| Manga Demon (en) | `en.mangademon` | demonicscans.org: the source of the whole library |
| MangaDex (all) | `all.mangadex` | second source |
| Webtoons (all) | `all.webtoons` | installed 2026-11-08 |

Local copies live in `extensions/` (currently `.jar`: the server converts each `.apk`). The
catalogue is third-party, so these copies are what survives it disappearing. After any
install or update, copy the new file in too and keep the old one.

## Check versions

```bash
tools/ext-check.ts          # local copy | installed on the server | catalogue
tools/ext-check.ts --quiet  # only rows that need action
```

On 2026-11-08 the catalogue had MangaDex 1.6.3 (local copy 1.6.1) and Manga Demon 1.6.1.

## The catalogue

`server.extensionStores = ["https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.pb"]`.

- **`index.min.json` is a retired 2-entry stub** ("Outdated App", "Update to Mihon"). Any
  client reading it sees exactly 2 extensions. Never use it.
- `index.pb` is gzipped but served **without** a `Content-Encoding` header, so gunzip it
  yourself: `curl -sL <url> | gunzip | strings | grep mangademon`.

## Install or update

- UI: Browse -> Extensions. API: `fetchExtensions`, then
  `updateExtension(input: {id: <pkgName>, patch: {update: true}})` (`install: true` for a new
  one). Recipes: `suwayomi-api/references/recipes.md`.
- **504 from the server** on `github.com/.../releases/download/...` while curl and the
  browser fetch the same URL fine: cause unknown. Workaround: download the `.apk` in a
  browser, then Browse -> Extensions -> **Install external extension**. A stale DNS entry
  for the CDN edge is one suspect (the JVM uses the system resolver): try
  `resolvectl flush-caches`, then `scripts/restart.ts`.

## A source stops working

1. `ext-check`: is there a newer version? Update first.
2. Server log (`<data>/logs/application.log`) for the HTTP status the source returns.
3. Cloudflare challenge: `kcefEnabled` is on (WebView). `flareSolverrEnabled` is off and needs
   a FlareSolverr instance (`flareSolverrUrl`) before turning it on.
4. Gone from the catalogue: install the local copy from `extensions/` as an external extension.
