---
name: suwayomi-api
description: Read or change Suwayomi server state through its GraphQL API, including server settings, web UI settings (global metadata), schema lookups, backups and library updates. Use for "set X", "what is configured", "change a reader setting", or before writing any query or mutation against this server.
---

# The Suwayomi GraphQL API

One endpoint: `POST $SUWAYOMI_URL/api/graphql` (default `http://127.0.0.1:4567`, from
`stack.conf`). Use the helper rather than hand-written curl:

```bash
tools/gql.ts '{ settings { webUIFlavor webUIUpdateCheckInterval } }'
tools/gql.ts --vars '{"id": 12}' 'query($id: Int!) { manga(id: $id) { title } }'
tools/gql.ts @query.graphql                # or - for stdin
tools/gql.ts --root                        # every query and mutation the server has
tools/gql.ts --type SetSettingsInput       # fields of any type
tools/gql.ts --mutate 'mutation { ... }'   # mutations are refused without --mutate
```

It flags known traps on stderr (see below). Exit 1 = GraphQL error, 3 = server not answering.

**Look the shape up before writing a new operation.** `gql --type` asks the live server.
Tsumiru's operations (`ui/Suwayomi-Tsumiru/lib/**/graphql/*.graphql`) show shapes that work.
Tested shapes: `references/recipes.md`.

**Mutations change the user's data and the server has no undo.** Say what will change before
running one. Batch many changes into one document with aliases (`a: updateChapter(...)`,
`b: updateChapter(...)`), so the user approves once.

## Server settings

- Change them with `setSettings`. It persists to `server.conf`.
- Do not edit `server.conf` while the server runs: on shutdown it rewrites the file from
  memory, so the edit is lost. Edit the file only with the server stopped.
- Settings wired at startup need a real restart: `webUIFlavor` (static routing),
  `webUIInterface`, `webUISubpath`. `ip` applies at once (the server rebinds, the request
  itself then fails with an HTTP 500 although the setting took: `server-ops`).
- Enum values are uppercase. `server.conf` writes some quoted (`"CUSTOM"`), some not
  (`BROWSER`). Both parse.
- The intended values, with reasons: `stack-doctor/references/expected-config.md`.

## UI settings

Tsumiru keeps its global display and reader settings in the **browser** (local storage), so
another browser or device starts from defaults. Per-series reader settings live on the server
as manga metadata, keys `flutter_reader*` (e.g. `flutter_readerMode = webtoon`):

```bash
tools/gql.ts '{ manga(id: 11) { meta { key value } } }'
```

The server's `webUI_*` global metadata belonged to the removed Suwayomi-WebUI. Tsumiru does
not read it.

## Server behaviour worth knowing

- **No server-side image cache.** `<data>/cache/` is KCEF (Chromium) only. Chapter pages are
  fetched from the source every time. The Manga Demon extension limits itself to ~2
  requests/s (`rateLimit(2)`). `autoDownloadNewChapters = true` would prefetch new chapters.
- `excludeUnreadChapters = true` (the default) SKIPS titles that still have unread chapters
  during library updates, which is exactly the backlog titles. Keep it `false`.
- `globalUpdateInterval` has a floor of 6.0 hours.
- `webUIUpdateCheckInterval` must stay 0 on the CUSTOM flavor, or the server may replace the
  custom UI.
- Backups: daily into `backups/` (`backupPath`), kept 60 days (`backupTTL`). They include
  manga, categories, chapters, tracking, history, client data and server settings.
- Library data, reading progress, chapter numbers: `library-progress` skill.
- Extensions and sources: `suwayomi-extensions` skill.
