"""The "upscaled" mark in the chapter list. It is a chapter meta entry on the server, which the
patched Tsumiru shows (ui/patches/suwayomi-tsumiru-upscaled-mark.patch).

Only readahead can tell that a chapter is upscaled: each page that it upscaled has a JPEG
comment (pages.is_upscaled). The server only knows that the chapter is downloaded. So a job tags
its chapter when it upscaled a page of it. sync() makes all tags agree with the files again, for
example after a pass or a person deletes a download.
"""

import pages
import suwayomi
from datatypes import TagChanges

KEY = "manga_stack_upscaled"  # the Tsumiru patch looks for this key


def tag(chapter_ids: list[int]) -> None:
    suwayomi.set_chapter_meta(chapter_ids, KEY, "true")


def sync() -> TagChanges:
    """Tag the downloaded chapters that are upscaled, and untag all others. Returns what
    changed."""
    # What the chapter list shows, and what the files say.
    tagged = suwayomi.chapters_with_meta(KEY)
    upscaled = {c.id for c in suwayomi.downloaded_chapters() if pages.is_upscaled(c)}

    # Tag the upscaled chapters that are not tagged. Untag the tagged chapters that are not upscaled.
    added, removed = sorted(upscaled - tagged), sorted(tagged - upscaled)
    if added:
        suwayomi.set_chapter_meta(added, KEY, "true")
    if removed:
        suwayomi.delete_chapter_meta(removed, KEY)
    return TagChanges(tagged=added, untagged=removed)
