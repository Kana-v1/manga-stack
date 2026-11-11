# GraphQL recipes for this server

Shapes taken from what the Suwayomi web UIs send, input types checked against the live
v2.4.2366 schema.
Where a field list is shortened, `gql --type <Type>` gives the full one.

## Settings

```graphql
{ settings { ip port webUIFlavor webUIUpdateCheckInterval excludeUnreadChapters
             globalUpdateInterval backupPath backupTTL extensionStores } }
```

```graphql
mutation { setSettings(input: { settings: { webUIUpdateCheckInterval: 0 } }) {
  settings { webUIUpdateCheckInterval } } }
```

## Global metadata (web UI settings)

```graphql
{ metas { nodes { key value } } }
```

```graphql
mutation($k: String!, $v: String!) {
  setGlobalMeta(input: { meta: { key: $k, value: $v } }) { meta { key value } } }
```
with `--vars '{"k": "<key>", "v": "<value>"}'`. Checked against v2.4.2366.

## Manga and chapters

```graphql
{ mangas(condition: { inLibrary: true }) { nodes {
    id title unreadCount source { displayName }
    lastReadChapter { chapterNumber lastReadAt }
    highestNumberedChapter { chapterNumber } } } }
```

```graphql
query($id: Int!) { manga(id: $id) { title chapters { nodes {
    id chapterNumber name sourceOrder isRead lastPageRead pageCount lastReadAt } } } }
```

```graphql
mutation($ids: [Int!]!) {
  updateChapters(input: { ids: $ids, patch: { isRead: true } }) {
    chapters { id isRead lastReadAt } } }
```

```graphql
mutation($id: Int!, $page: Int!) {
  updateChapter(input: { id: $id, patch: { lastPageRead: $page } }) {
    chapter { id isRead lastPageRead lastReadAt } } }
```

Why the two are different, and in which order to run them: `library-progress` skill.

## Extensions

```graphql
{ extensions(condition: { isInstalled: true }) { nodes {
    pkgName name lang versionName hasUpdate isObsolete } } }
```

```graphql
mutation { fetchExtensions(input: {}) { extensions { pkgName versionName hasUpdate } } }
```

```graphql
mutation($pkg: String!) {
  updateExtension(input: { id: $pkg, patch: { update: true } }) {
    extension { pkgName versionName hasUpdate } } }
```
`patch` also takes `install: true` or `uninstall: true`. `id` is the `pkgName`.

## Backups and library update

```bash
tools/gql.ts --type CreateBackupInput       # flags for what to include
```
```graphql
mutation { createBackup(input: {}) { url } }
```
The web UIs also pass include flags. Check `--type` if `{}` is rejected. Run one before any
bulk change to reading progress.

```bash
tools/gql.ts --root | tr ' ' '\n' | grep -i update   # updateLibrary* and friends
```

Update the whole library (titles the server's settings exclude are skipped), then follow it:
```graphql
mutation { updateLibrary(input: {}) { clientMutationId } }
```
```graphql
{ lastUpdateTimestamp { timestamp } libraryUpdateStatus { jobsInfo { isRunning totalJobs finishedJobs } } }
```
For ~0.2 s after the mutation the status still shows the previous update as finished. The
server sets `lastUpdateTimestamp` (ms) when an update starts: done = stamp from now on and
`isRunning` false (`readahead/suwayomi.py update_library`). Checked against v2.4.2366.

## Downloads and chapter metadata

```graphql
mutation($ids: [Int!]!) { deleteDownloadedChapters(input: {ids: $ids}) { clientMutationId } }
```
```graphql
mutation($ids: [Int!]!, $key: String!, $value: String!) {
  setChapterMetas(input: {items: [{chapterIds: $ids, metas: [{key: $key, value: $value}]}]}) {
    clientMutationId } }
```
```graphql
mutation($ids: [Int!]!, $key: String!) {
  deleteChapterMetas(input: {items: [{chapterIds: $ids, keys: [$key]}]}) { clientMutationId } }
```
`ChapterFilterInput` cannot filter by meta: read `chapters { nodes { id meta { key } } }`.
Checked against v2.4.2366.
