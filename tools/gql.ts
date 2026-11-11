#!/usr/bin/env bun
// Talk to the Suwayomi GraphQL API (<SUWAYOMI_URL>/api/graphql). Prints the `data` as JSON.

import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { GqlError, gql, ServerDown } from "../scripts/lib.ts";

const USAGE = `
tools/gql.ts '{ settings { webUIFlavor } }'
tools/gql.ts --vars '{"id":1010}' 'query($id:Int!){ chapter(id:$id){ name isDownloaded } }'
tools/gql.ts @query.graphql          read the document from a file ( - reads stdin)
tools/gql.ts --type MangaType        fields of a schema type (input types: their input fields)
tools/gql.ts --root                  every query and mutation the server offers

A document containing \`mutation\` is refused without --mutate, and the harness asks the user
before any --mutate call runs. Known traps are flagged on stderr. Exit 1 on GraphQL errors,
2 on usage errors, 3 when the server does not answer.`;

const TYPE_QUERY = `query($n:String!){ __type(name:$n){ name kind
  fields { name args { name type { ...T } } type { ...T } }
  inputFields { name type { ...T } }
  enumValues { name } } }
fragment T on __Type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }`;

type TypeRef = { kind: string; name: string | null; ofType: TypeRef | null };

/** A schema type as GraphQL writes it: [Int!]! */
function typeName(t: TypeRef): string {
  if (t.kind === "NON_NULL") return `${typeName(t.ofType!)}!`;
  if (t.kind === "LIST") return `[${typeName(t.ofType!)}]`;
  return t.name ?? "?";
}

/** Warnings for mistakes this project has already made once. */
function traps(doc: string): string[] {
  const out: string[] = [];
  if (/\bupdateChapters?\b/.test(doc) && /\bisRead\b/.test(doc) && !/\blastPageRead\b/.test(doc)) {
    out.push("isRead alone does NOT stamp lastReadAt, so manga.lastReadChapter stays wrong (library cards then show " +
      "'chapter 1'). Also patch lastPageRead on the chapter; the server stamps lastReadAt then.");
  }
  if (/\bsetSettings\b/.test(doc) && /\b(webUIFlavor|webUIInterface|webUISubpath)\b/.test(doc)) {
    out.push("this setting is wired at startup: it takes effect only after a real server restart.");
  }
  if (/\bsetSettings\b/.test(doc) && /\b(ip|port)\b/.test(doc)) {
    out.push("ip/port apply at once: the server rebinds, so this request may fail with an HTTP 500 although the " +
      "setting took. Check with { settings { ip port } }.");
  }
  if (/\bchapters\b[^}]*\btotalCount\b/s.test(doc)) {
    out.push("chapters.totalCount counts chapter ROWS, not the latest chapter number (decimal chapters such as 81.1 " +
      "make them differ). Use highestNumberedChapter.chapterNumber.");
  }
  return out;
}

async function root() {
  // One root per request: the server rejects introspection that asks for `fields` twice.
  for (const [rootType, label] of [["queryType", "queries:  "], ["mutationType", "mutations:"]]) {
    const data = await gql(`{ __schema { ${rootType} { fields { name } } } }`);
    const fields: { name: string }[] = data.__schema[rootType]?.fields ?? [];
    console.log(label, fields.map((f) => f.name).sort().join(" "));
  }
}

async function describeType(name: string): Promise<number> {
  const t = (await gql(TYPE_QUERY, { n: name })).__type;
  if (!t) {
    console.error(`no type ${name}`);
    return 1;
  }
  for (const f of t.fields ?? []) {
    const args = f.args.map((a: { name: string; type: TypeRef }) => `${a.name}: ${typeName(a.type)}`).join(", ");
    console.log(`${f.name}${args ? `(${args})` : ""}: ${typeName(f.type)}`);
  }
  for (const f of t.inputFields ?? []) console.log(`${f.name}: ${typeName(f.type)}`);
  for (const e of t.enumValues ?? []) console.log(e.name);
  return 0;
}

async function main(): Promise<number> {
  const { values: opts, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      vars: { type: "string", default: "{}" },
      mutate: { type: "boolean" },
      type: { type: "string" },
      root: { type: "boolean" },
      help: { type: "boolean", short: "h" },
    },
  });
  if (opts.help) {
    console.log(USAGE.trim());
    return 0;
  }
  try {
    if (opts.root) {
      await root();
      return 0;
    }
    if (opts.type) return await describeType(opts.type);

    let doc = positionals[0];
    if (!doc) {
      console.error(USAGE.trim());
      return 2;
    }
    if (doc === "-") doc = await Bun.stdin.text();
    else if (doc.startsWith("@")) doc = readFileSync(doc.slice(1), "utf8");
    if (/^\s*mutation\b/m.test(doc) && !opts.mutate) {
      console.error("refused: this is a mutation. Re-run with --mutate (the user will be asked to approve).");
      return 2;
    }
    for (const w of traps(doc)) console.error(`gql warning: ${w}`);
    console.log(JSON.stringify(await gql(doc, JSON.parse(opts.vars!)), null, 2));
    return 0;
  } catch (err) {
    if (err instanceof GqlError) {
      console.error(`GraphQL error: ${JSON.stringify(err.errors, null, 2)}`);
      return 1;
    }
    if (err instanceof ServerDown) {
      console.error(`server ${err.message}`);
      return 3;
    }
    throw err;
  }
}

process.exit(await main());
