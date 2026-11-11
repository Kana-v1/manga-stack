#!/usr/bin/env bun
// Print the library: one row per title with read progress against the latest chapter.
//
// "read" is lastReadChapter.chapterNumber and "latest" is highestNumberedChapter.chapterNumber.
// Never chapters.totalCount: that counts rows, and decimal chapters (81.1, 82.5) make it differ.

import { flags, GqlError, gql, ServerDown } from "../scripts/lib.ts";

const opts = flags(
  `
tools/library.ts             every title, sorted by title
tools/library.ts --behind    only titles with unread chapters
tools/library.ts --json      raw rows for scripts`,
  ["--behind", "--json"],
);

const QUERY = `{ mangas(condition: {inLibrary: true}) { nodes {
  id title unreadCount
  source { displayName }
  lastReadChapter { chapterNumber lastReadAt }
  highestNumberedChapter { chapterNumber } } } }`;

type Row = {
  id: number;
  title: string;
  unreadCount: number;
  source: { displayName: string } | null;
  lastReadChapter: { chapterNumber: number; lastReadAt: string } | null;
  highestNumberedChapter: { chapterNumber: number } | null;
};

let rows: Row[];
try {
  rows = (await gql(QUERY)).mangas.nodes;
} catch (err) {
  if (err instanceof GqlError) {
    console.error(`GraphQL error: ${err.message}`);
    process.exit(1);
  }
  if (err instanceof ServerDown) {
    console.error(`server ${err.message}`);
    process.exit(3);
  }
  throw err;
}

rows.sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));
if (opts.has("--behind")) rows = rows.filter((r) => r.unreadCount);
if (opts.has("--json")) {
  console.log(JSON.stringify(rows, null, 2));
  process.exit(0);
}

/** 12 for 12.0, 81.1 for 81.1, - for none. */
const num = (chapter: { chapterNumber: number } | null) => (chapter?.chapterNumber == null ? "-" : String(chapter.chapterNumber));

const width = Math.min(Math.max(5, ...rows.map((r) => r.title.length)), 48);
console.log(`${"id".padStart(5)}  ${"title".padEnd(width)}  ${"read".padStart(7)}  ${"latest".padStart(7)}  ${"unread".padStart(6)}  source`);
for (const r of rows) {
  console.log(
    `${String(r.id).padStart(5)}  ${r.title.slice(0, width).padEnd(width)}  ${num(r.lastReadChapter).padStart(7)}  ` +
      `${num(r.highestNumberedChapter).padStart(7)}  ${String(r.unreadCount).padStart(6)}  ${r.source?.displayName ?? "?"}`,
  );
}
console.log(`${rows.length} titles, ${rows.filter((r) => r.unreadCount).length} with unread chapters`);
