"""What a pass would do, for each library title. This module only reads, and changes nothing.

- Upscale: the next AHEAD unread chapters after the furthest chapter read (the first AHEAD
  chapters when nothing is read).
- Text: of the next OCR_AHEAD unread chapters, those whose text is not read (ocr.py).
- Delete: the downloads that readahead made (download_record.py) of chapters that are now read.

"After the furthest chapter read" is important. Unread chapters before it are behind the reader,
so they are not worth upscaling. These are chapters that the reader skipped, or reopened (which
marks them unread again).
"""

import download_record
import ocr
import pages
import suwayomi
from config import AHEAD, OCR_AHEAD
from datatypes import Chapter, LibraryManga, TitlePlan, UpscaleChapter


def plan() -> list[TitlePlan]:
    """What a pass would do, for every library title, sorted by title."""
    recorded = download_record.load()
    library = sorted(suwayomi.library(), key=lambda m: m.title.lower())
    return [plan_title(manga, recorded) for manga in library]


def plan_title(manga: LibraryManga, recorded: set[int]) -> TitlePlan:
    """What a pass would do for one title. `recorded` are the chapters whose download
    readahead made (download_record.py)."""
    # The chapters in reading order. source_order is the place of a chapter in the title: 1 is first.
    chapters = sorted(manga.chapters.nodes, key=lambda c: c.source_order)

    # Where the reader is: the furthest chapter read, and the unread chapters after it.
    read = [c for c in chapters if c.is_read]
    last_read = read[-1] if read else None
    after = last_read.source_order if last_read else 0
    unread_chapters = [c for c in chapters if not c.is_read and c.source_order > after]

    # To upscale: the next AHEAD unread chapters. Get each one again, with all its fields. The
    # library query gets few fields, and the download folder needs all of them.
    upscale = [upscale_chapter(suwayomi.chapter(c.id)) for c in unread_chapters[:AHEAD]]

    # To read the text of: the next OCR_AHEAD unread chapters whose text is not read.
    text = [c for c in unread_chapters[:OCR_AHEAD] if not ocr.has_text(c.id)]

    # To delete: the downloads that readahead made of chapters that are now read.
    delete = [c for c in read if c.is_downloaded and c.id in recorded]

    return TitlePlan(
        manga_id=manga.id, title=manga.title, last_read=last_read, upscale=upscale, text=text, delete=delete
    )


def upscale_chapter(ch: Chapter) -> UpscaleChapter:
    """The chapter, and whether it is done (no page needs an upscale)."""
    return UpscaleChapter(**dict(ch), done=pages.is_done(ch))
