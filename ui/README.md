# The UI: Suwayomi-Tsumiru, with our changes

The reader is [Suwayomi-Tsumiru](https://github.com/Suwayomi/Suwayomi-Tsumiru), a Flutter web
app, built from source. This folder holds only our changes to it, as patch files: diffs against
the upstream release (`TSUMIRU_VERSION` in `stack.conf`). Upstream's code is not in this repo.
The build clones it into `ui/Suwayomi-Tsumiru/` (git-ignored) and applies the patches on top.
This is the usual way to keep changes to the code of a different project. The name for it is a
"patch series". Debian packages and browser forks keep their changes the same way.

```
ui/
  patches/*.patch     our changes, one feature per patch
  patches/series      the order they apply in: each one may build on the ones before it
  apply.ts            clone (if needed), reset to the release tag, apply the series
  patch-tool.ts       check the series, and edit one patch at a time (below)
  clone.ts            the code apply.ts, patch-tool.ts and the build share
  Suwayomi-Tsumiru/   the upstream clone (not in git)
```

## The patches

| Patch | Does |
|---|---|
| `suwayomi-tsumiru-reader-html-images.patch` | long strip on the web: the pages are browser `<img>` elements, not GPU textures. Thus upscaled strips taller than 16,384 px (the GPU texture limit) keep their full resolution |
| `suwayomi-tsumiru-upscaled-mark.patch` | chapter list: an "HD" icon on downloaded chapters with the chapter meta `manga_stack_upscaled`, which readahead sets |
| `suwayomi-tsumiru-bubble-text.patch` | long strip: invisible boxes over the speech bubbles, from readahead's text recognition (`/api/ocr` on port 8765). A click on one copies its text |
| `suwayomi-tsumiru-tap-zones-beside-page.patch` | long strip: only the margins beside the page column are tap zones, so a click on the page reaches its bubbles |
| `suwayomi-tsumiru-click-scroll-stops.patch` | long strip: a forward click or key stops at the next bubble or panel below the reading line, never further than "Scroll amount". Its settings sit next to "Scroll amount" |

## Building

```bash
scripts/build-ui.ts                   # apply the series, build, install for the server
scripts/rebuild-and-start.ts --ui-only   # the same, then restart the server and check it serves the build
ui/apply.ts                           # only apply: the patched source, without building
```

A build calls itself `<TSUMIRU_VERSION>+<first 8 hex digits of a sha256 over the patches>`, so any
change to a patch gives a new revision. The server answers it at `/revision`. The browser keeps
the old app until a hard reload (Ctrl+F5).

## Changing a patch

After a build, the clone holds every patch at once, so `git diff` in it mixes them all. Edit one
patch at a time with `patch-tool.ts`, which sets the clone up for exactly that patch and writes
the diff back:

```bash
ui/patch-tool.ts status               # which state the clone is in
ui/patch-tool.ts workon NAME.patch    # clone = release tag + the patches before NAME + NAME
#   ...edit files under ui/Suwayomi-Tsumiru/lib/...
ui/patch-tool.ts export               # writes ui/patches/NAME.patch and checks the series
scripts/rebuild-and-start.ts --ui-only
```

- A new patch: `workon` a new name (it starts on top of the series), and add its file name to
  `patches/series`.
- The build resets the clone, so edits that are in no patch file are lost. The build and
  `apply.ts` refuse to run over them. `patch-tool.ts status --diff` shows them, `salvage NEW.patch`
  saves them as a new patch.
- Keep a patch small and in upstream's style, so it keeps applying after an upgrade. Upstream's
  files are not `dart format`-clean under this SDK: format only your own lines.

## Upgrading Tsumiru

Set `TSUMIRU_VERSION` in `stack.conf` (Tsumiru's compatibility table says which server it
needs), then `ui/patch-tool.ts check`. For a patch that no longer applies:
`ui/patch-tool.ts workon NAME.patch --3way`, resolve the conflicts, `export`.
