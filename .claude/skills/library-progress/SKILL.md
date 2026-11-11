---
name: library-progress
description: Work with the manga library and reading progress in Suwayomi: list titles and how far each is read, and find the latest chapter. Mark chapters read or unread so the server records it properly, sync progress from another site, and migrate titles between sources. Use for "what am I behind on", "mark up to chapter N read", "sync my progress" or "why does the card say chapter 1". Also use for any bulk change to read state.
---

# Library and reading progress

## The library

35 titles, migrated from DemonicScans bookmarks. The **Manga Demon** extension is
demonicscans.org, so that migration was same-source and lossless, and read progress was
synced to match DemonicScans exactly at the time.

```bash
tools/library.ts             # title, read, latest, unread, source
tools/library.ts --behind    # only titles with unread chapters
tools/library.ts --json      # rows with manga ids, for scripts
```

## Two numbers that are easy to get wrong

- **Latest chapter = `highestNumberedChapter.chapterNumber`.** Never `chapters.totalCount`:
  that counts chapter rows, and decimal chapters (81.1, 82.5) make the two differ.
- **Last read = `lastReadChapter`**, which is the chapter with the newest `lastReadAt`.
  Marking chapters read in bulk with `updateChapters(... isRead: true)` does **not** set
  `lastReadAt`. The library cards then showed "chapter 1". `lastReadAt` cannot be set
  directly: patch `lastPageRead` on a chapter and the server stamps `lastReadAt` itself.
- **Re-opening a read chapter can make it unread.** A read chapter was opened in the
  reader at page 1 and came back `isRead: false`, `lastPageRead: 0`
  (2026-11-09). Readahead then treats it as the next unread chapter. Fix: mark it read,
  then re-stamp the chapter actually being read (steps 3-4 below).

## Mark a title read up to chapter N

1. `library --json` to get the manga id. Then its chapters (recipe in
   `suwayomi-api/references/recipes.md`): `id chapterNumber isRead lastPageRead pageCount`.
2. Show the user the plan as a table (title, current read, new read) before changing anything.
   For more than a couple of titles, run `createBackup` first.
3. `updateChapters(input: {ids: [every chapter <= N], patch: {isRead: true}})`.
4. Then `updateChapter` on chapter N alone with `patch: {lastPageRead: <pageCount - 1, or 1
   when pageCount is 0>}`. Do it last: the newest `lastReadAt` decides `lastReadChapter`.
5. Check: `library` shows N under "read" for that title.

Unread is the reverse: `isRead: false` on the chapters above N, then re-stamp chapter N as in
step 4 so `lastReadChapter` points at it.

Put all titles' mutations in one document with aliases, so the user approves once:
`m1: updateChapters(...) {...} m2: updateChapter(...) {...}`.

## Sync progress from another site

1. Get the other side's progress per title as chapter numbers (the user exports or pastes it).
2. Match titles to manga ids with `library --json`. Titles differ in punctuation and
   subtitles. Show unmatched and doubtful matches to the user instead of guessing.
3. Dry-run table: title, Suwayomi read, target read, change. Only rows that change.
4. After approval, apply per title with the steps above, then compare with `library` again.

## Migrate a title to another source

Tsumiru has a migrate flow (series page -> migrate). It moves read state between sources by
matching chapter numbers, so check the decimal chapters afterwards. Same-source migration
(the DemonicScans case) is lossless.
