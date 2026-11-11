---
name: ui-patch
description: Change, build, deploy or debug the reader UI, Suwayomi-Tsumiru (a Flutter web app) built from source with local patch files. Use when changing reader or library behaviour, when a Tsumiru patch stops applying, or when the Flutter build fails. Also use after an upgrade of Tsumiru, or when the UI looks wrong, stale or blurry.
---

# The UI: Tsumiru, patched

The server serves Tsumiru from `<data>/webUI` (`webUIFlavor = CUSTOM`). It is upstream
Suwayomi-Tsumiru at the `TSUMIRU_VERSION` tag plus the patches in `ui/patches`, in the order of `ui/patches/series`
(`stack.conf`), built by `scripts/build-ui.ts` with the Flutter SDK pinned in `stack.conf`
(`FLUTTER_VERSION`, kept in `.cache/flutter`). A UI change exists only as a patch file in
`ui/patches/`. Never edit `<data>/webUI`: the next build replaces it. The patch list, the
loop and the upgrade steps for people: `ui/README.md`.

What each patch does: the table in `ui/README.md`.

## The loop

```bash
ui/patch-tool.ts status               # pristine | deployed | workon | DIRTY
ui/patch-tool.ts workon NAME.patch    # clone = tag + patches before NAME + NAME
#   ...edit files under ui/Suwayomi-Tsumiru/lib/...
cd ui/Suwayomi-Tsumiru && ../../.cache/flutter/bin/flutter analyze <changed files>  # dart-run-static-analysis
ui/patch-tool.ts export               # writes ui/patches/NAME.patch (LF) and checks the series
scripts/rebuild-and-start.ts --ui-only   # build (~2 min), install, restart, check it is served
```

- A new patch starts on top of the series. Add its file name to `ui/patches/series` and commit both.
- Edits made without a workon: `patch-tool status --diff`, then `patch-tool salvage NEW.patch`.
  The build resets the clone, so edits in no patch are lost.
- **Formatting:** upstream's files are not `dart format`-clean under this SDK version. Do not
  reformat their code. Format only your own lines (compare with `dart format --output=show`).
- Keep diffs small and in upstream's style: every patch must keep applying after an upgrade.
- The build's revision is `TSUMIRU_VERSION+<hash of the patches>`, so any patch change gives a
  new revision. Generated code (`*.g.dart`, `*.graphql.dart`, l10n) is git-ignored and made
  at build time by `build_runner` / `gen-l10n`.

## Prove it is live

`scripts/rebuild-and-start.ts --ui-only` fails unless the server serves the new revision.
`tools/doctor.ts` compares served, installed and expected revisions. The browser keeps the
old app until a hard reload: **Ctrl+F5**.

## Flutter on the web: what bit us

- **GPU texture limit.** Tsumiru paints on a WebGL canvas, and one image is one texture,
  capped at the browser's `MAX_TEXTURE_SIZE` (16384 px on the user's machine). Tsumiru's
  `TextureLimitedImageProvider` shrinks anything taller, so an upscaled 800x12,810 strip
  (1600x25,620) came out ~1,023 px wide and softer than the original. The browser's own
  image viewer has no such limit.
- **The fix in the patch:** `ServerImage(preferHtmlElementOnWeb: true)` in the long-strip
  reader uses `NetworkImage(..., webHtmlElementStrategy: WebHtmlElementStrategy.prefer)`, the
  path Tsumiru already used for external covers: a real `<img>` element in a platform view.
  Costs: somewhat heavier scrolling. Opacity, colour filters and the reader's brightness and
  colour overlays (`BackdropFilter`) do not apply to pages. Requests must need no headers
  (no basic/simple-login auth, no custom headers), otherwise it falls back to the texture path.
- `ImageRenderMethodForWeb.HtmlImage` in `cached_network_image` does **not** help: it still
  decodes into a texture.
- `splitTallImages` (slicing tall pages into textures) is native-only: it reads the cached
  file with `dart:io`, which the web build cannot.
- Paged reader modes cut wide pages from decoded pixels, so they stay on the texture path.

## Upgrading Tsumiru

1. Its `versionToServerVersionMapping.json` must pair the new version with the server's
   revision (v1.6.5 <-> r2366). A UI ahead of its server breaks in odd ways.
2. Check its `.fvmrc`: a new Flutter version means new `FLUTTER_VERSION` and `FLUTTER_SHA256`
   (sha256 from `https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json`).
3. Set `TSUMIRU_VERSION`, run `ui/patch-tool.ts check`. For each broken patch
   `patch-tool workon NAME --3way`, resolve, `export`.
4. `scripts/rebuild-and-start.ts --ui-only`, then look at a tall chapter in the reader.

## When the UI looks wrong

Evidence before theories (`systematic-debugging`):

- `/revision` compared with `doctor`'s expected revision.
- The raw page (`/api/v1/manga/<id>/chapter/<index>/page/<n>`) compared with the reader. This
  separates image problems from rendering problems.
- The browser console and `<data>/logs/application.log`.

## Roll back

```bash
rm -rf ~/.local/share/Tachidesk/webUI && mv ~/.local/share/Tachidesk/webUI.prev ~/.local/share/Tachidesk/webUI
scripts/restart.ts
```
