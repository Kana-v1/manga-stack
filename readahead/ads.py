#!/usr/bin/env python3
"""Ads in chapters: the panels that scanlators add. These are donation and Discord appeals,
credits cards, and "read this chapter at <site>" notices and banners. This module finds them
through the text of the chapter (ocr.py) and cuts them out of the page strips. The panels and
credits of the original stay.

    ads.py <chapterId> [preview folder]   dry run: show the cuts, and save a before/after
                                          preview of each cut in the folder

The upscale job (jobs.py) makes the cuts. pages.process() cuts the ad rows out of a page before
it upscales the page. Then shift() moves the saved text boxes of the page to match.

How a cut is found:
1. Each page is divided into panels. A panel is the rows between two gaps. A gap is a run of rows
   of one colour, at least GAP page widths tall. Each text region belongs to the panel that holds
   most of its box.
2. Ad text (AD_TEXT) is a phrase that only a scanlator's panel contains. Examples: "ko-fi",
   "discord.gg/...", "read this chapter at <site>", a staff role alone ("TRANSLATOR"). A site
   name alone is not ad text, because sites also put badges with their name on story panels.
3. Each panel with ad text is cut, with the gap below it. Then one gap stays between the panels
   that remain. The last panel on a page takes the gap above it instead. A panel is not cut when:
   - It contains a speech bubble of the story. A bubble that touches ad text, or that is the
     title, does not count. The detector sees boxed ad text ("ALERT! ...") and the title plate
     of a credits card as bubbles. A panel with MANY ad texts (a credits card) is always cut.
   - It is taller than MAX_CUT page widths. Then the gaps were not found, and the "panel" would
     contain story too.
4. A page that is one ad panel is cut whole. Its file becomes one row, because the server needs
   every page. A landscape page that is one panel with ad text is the banner of a site. It is
   cut even when something on it looks like a bubble ("FASTEST UPDATES").
"""

import io
import itertools
import os
import re
import sys
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw

import suwayomi
from config import OCR_DIR
from datatypes import Chapter, ChapterText, Region, TextPage

Image.MAX_IMAGE_PIXELS = 400_000_000  # webtoon strips are tall

AD_TEXT = re.compile(
    r"ko-?fi\b|discord\.gg|\.gg/discord|join (our|the) discord|patreon"
    r"|consider donating|help us with donations|support us (at|on|by)|you should be reading this"
    r"|^read at$|\b(read|play)\b[^.]{0,40}\bat \S+\.(com|org|net|cc|gg|io|me|to)\b|we are recruiting"
    r"|dear \w+ readers|brought to you by"
    # a staff role on its own, as credits list them ("—REDRAWER", "TYPESETTER STAFF")
    r"|^\W*(translator|proofreader|typesetter|redrawer|quality checker|cleaner)\b.{0,20}$",
    re.IGNORECASE,
)
GAP = 0.01  # the shortest gap between panels, in page widths
PANEL_GAP = 0.05  # the shortest gap that starts a new panel for the reader's click-scroll
MAX_CUT = 3.5  # the tallest cut, in page widths (two ad panels touching can be 3.4)
MANY = 3  # this many ad texts make a panel an ad panel, whatever else it holds

# A row is "of one colour" (find_gaps) when almost all of its pixels are near the median
# brightness of the row. NOISE is how near, in brightness steps of 0-255. JPEG noise stays inside
# it. The border line of a panel does not
NOISE = 24
OFF_MEDIAN_SHARE = 0.002  # share of the row's pixels that may be further away (dust, a stray dot): 0.2%

# Decimal places kept for a fraction of the page height. 5 places are 1/100,000 of the page,
# less than a pixel of a 25,000 px strip. More places only make the saved JSON longer.
DIGITS = 5


class Rows(NamedTuple):
    """A run of rows of a page. It unpacks like a pair: `top, bottom = rows`."""

    start: int  # the first row
    end: int  # the row after the last one, so end - start is the number of rows


class Panel(NamedTuple):
    """A panel of a page, given as the gap above it and the gap below it (find_panels)."""

    gap_above: Rows
    gap_below: Rows

    @property
    def top(self) -> int:
        """The first row of the panel: the row where the gap above it ends."""
        return self.gap_above.end

    @property
    def bottom(self) -> int:
        """The row after the panel: the row where the gap below it starts."""
        return self.gap_below.start


def find_cuts(
    img: Image.Image, regions: list[Region], title: str
) -> tuple[list[Rows], list[tuple[Rows, str]]]:
    """Returns two lists. The first is the rows to cut out of the page, as [(top, bottom)], with
    bottom exclusive. The second is the panels with ad text that stay, as [((top, bottom),
    reason)]."""
    w, h = img.size
    panels = find_panels(img)
    cuts: list[Rows] = []
    refused: list[tuple[Rows, str]] = []

    for panel in panels:
        # 1. The text on this panel, and the ad text among it. A panel without ad text stays.
        texts = [r for r in regions if belongs(r, panels, h) == panel]
        ads = [r for r in texts if AD_TEXT.search(r.text)]
        if not ads:
            continue

        # 2. The rows to cut: the panel and the gap below it, so one gap stays between the panels
        #    that are left. The last panel on the page has no gap below it (only the bottom edge
        #    of the page). It takes the gap above it instead.
        is_last = panel.gap_below.start >= h
        if is_last:
            cut = Rows(panel.gap_above.start, h)
        else:
            cut = Rows(panel.top, panel.gap_below.end)

        # 3. Do not cut the panel if the cut would also remove story. A speech bubble of the
        #    story shows story, except on a banner page or in a panel with MANY ad texts. A
        #    banner page is one panel (no gaps found), and wider than it is tall.
        story = [r for r in texts if r.kind == "bubble" and is_story(r, ads, title)]
        is_banner = (panel.top, panel.bottom) == (0, h) and h < w
        # An ad panel is a short card. A "panel" taller than MAX_CUT page widths is several
        # panels with a gap that find_gaps did not see (the art goes across it). It can contain
        # story too.
        height = panel.bottom - panel.top

        if story and len(ads) < MANY and not is_banner:
            refused.append((cut, f"holds a speech bubble: {story[0].text[:40]!r}"))
        elif height > MAX_CUT * w:
            refused.append((cut, f"{height / w:.1f} page widths tall"))
        else:
            cuts.append(cut)

    return merge(cuts), refused


def find_panels(img: Image.Image) -> list[Panel]:
    """The page's panels: the rows between its gaps (find_gaps), each given as the gaps above
    and below it. The page's top and bottom edges count as empty gaps."""
    w, h = img.size
    gaps = find_gaps(np.asarray(img.convert("L")), int(GAP * w))
    # The top and bottom edges of the page count as gaps of no rows.
    edges = [Rows(0, 0), *gaps, Rows(h, h)]

    panels: list[Panel] = []
    for gap_above, gap_below in itertools.pairwise(edges):  # each gap, with the gap after it
        panel = Panel(gap_above, gap_below)
        # No rows between the two gaps: a gap touches the edge of the page. No panel there.
        if panel.top < panel.bottom:
            panels.append(panel)
    return panels


def merge(cuts: list[Rows]) -> list[Rows]:
    """Sorts the cuts and joins the cuts that overlap. Cuts overlap when two ad panels at the
    bottom of a page both take the gap between them."""
    merged: list[Rows] = []
    for cut in sorted(cuts):  # from the top of the page down
        last = merged[-1] if merged else None
        if last is not None and cut.start <= last.end:
            # The cut starts inside the last cut (or where it ends): the last cut gets longer.
            merged[-1] = Rows(last.start, max(last.end, cut.end))
        else:
            merged.append(cut)
    return merged


def cut(img: Image.Image, cuts: list[Rows]) -> Image.Image:
    """The page without the rows of the cuts. A page cut whole becomes one white row: the
    server needs every page file to be there."""
    # 1. The rows to keep: those between the cuts (sorted, not overlapping: merge()).
    kept: list[Rows] = []
    y = 0  # the first row after the last cut
    for top, bottom in cuts:
        if top > y:
            kept.append(Rows(y, top))
        y = bottom
    if y < img.height:
        kept.append(Rows(y, img.height))
    if not kept:
        return Image.new("RGB", (img.width, 1), "white")

    # 2. A new page, with the kept rows one under the other.
    out = Image.new("RGB", (img.width, sum(rows.end - rows.start for rows in kept)))
    y = 0  # where the next kept rows go on the new page
    for rows in kept:
        out.paste(img.crop((0, rows.start, img.width, rows.end)), (0, y))
        y += rows.end - rows.start
    return out


def shift(text: TextPage, cuts: list[tuple[float, float]]) -> None:
    """Changes the saved text of one page (one page of the ocr.py result) to match the page
    after the cuts. The cuts are fractions of the page height. Text regions and panel tops in a
    cut go. Those below a cut move up."""
    kept = max(1 - sum(b - t for t, b in cuts), 1e-6)  # the share of the page left (never 0)

    def moved(y: float) -> float:
        """Returns the position of height y on the new page. y is a fraction of the old page.
        The rows cut above y are subtracted, and the result is a fraction of the height that is
        left."""
        return round((y - sum(min(b, y) - t for t, b in cuts if t < y)) / kept, DIGITS)

    # Text regions: a region that is mostly inside a cut goes. Ad text that a cut touches at all
    # also goes. If it stayed, its box would reach into the next panel. Then a later run would
    # cut that panel too.
    regions: list[Region] = []
    for r in text.regions:
        x0, y0, x1, y1 = r.box
        shared = [min(y1, b) - max(y0, t) for t, b in cuts]  # its rows inside each cut (<= 0: none)
        if any(rows > 0.5 * (y1 - y0) for rows in shared) or (
            AD_TEXT.search(r.text) and any(rows > 0 for rows in shared)
        ):
            continue
        regions.append(Region(box=[x0, moved(y0), x1, moved(y1)], kind=r.kind, text=r.text))
    text.regions = regions

    # Panel tops and the page's height, likewise.
    if text.panels is not None:
        text.panels = [moved(panel) for panel in text.panels if not any(t <= panel < b for t, b in cuts)]
    if text.height is not None:
        text.height = max(1, round(text.height * kept))


def same_page(text: TextPage, size: tuple[int, int]) -> bool:
    """True when the saved text was read from this page, or from its upscaled version: the two
    have the same shape. A source can change the pages of a chapter after its text was read."""
    w, h = size
    if text.width is None or text.height is None:  # a page the source could not deliver
        return False
    return abs(text.height / text.width - h / w) < 0.01 * h / w


def panel_tops(img: Image.Image) -> list[float]:
    """Where panels start on a page, as fractions of its height: the first row after each gap of
    at least PANEL_GAP page widths. ocr.py saves them with the text of the page. The click-
    scroll of the reader stops there, and at speech bubbles. Smaller gaps (white space around a
    bubble in a panel) do not count, so a click does not stop every few rows."""
    w, h = img.size
    gaps = find_gaps(np.asarray(img.convert("L")), int(PANEL_GAP * w))
    # A panel starts where a gap ends. A gap that ends at the bottom of the page starts no panel.
    return [round(gap.end / h, DIGITS) for gap in gaps if gap.end < h]


def find_gaps(gray: npt.NDArray[np.uint8], min_rows: int) -> list[Rows]:
    """Runs of at least min_rows rows of one colour, as [(first row, last row + 1)]. A row is of
    one colour when almost every pixel is near the median brightness of the row. JPEG noise
    stays near the median. The border line of a panel does not."""
    # 1. For every row: is it of one colour? `gray` is a table of brightness (0-255), one line
    #    of the table for each row of the page. Each numpy operation below works on all rows at
    #    once, and gives one value for each row.
    width = gray.shape[1]  # pixels in a row
    median = np.median(gray, axis=1, keepdims=True)  # the middle brightness of each row

    # For each row: how many of its pixels are more than NOISE away from its median. One number
    # per row, e.g. [0, 1, 37]. int16, because a subtraction of uint8 values wraps around below
    # 0 (3 - 5 = 254).
    off_median_pixels = (np.abs(gray.astype(np.int16) - median) > NOISE).sum(axis=1)
    # How many such pixels a row of one colour may have: 1.6 for a row of 800 pixels.
    max_off_median = width * OFF_MEDIAN_SHARE
    # Each count against that limit: one True or False per row, e.g. [True, True, False].
    # In other words: True where at least 99.8% of the row is one colour.
    blank = off_median_pixels <= max_off_median

    # 2. The runs of such rows that are long enough. groupby() splits the rows into runs of
    #    rows with the same value: blank rows, then not blank ones, and so on.
    gaps: list[Rows] = []
    y = 0  # the first row of the run

    # row:    0     1     2     3      4      5     6     7
    # blank:  False False True  True   True   False False True
    #          └─ art ─┘   └── gap ───┘        └─ art ─┘   └gap┘

    #  runs = (is_blank, length) of each run:
    #           (False, 2)       (True, 3)       (False, 2)    (True, 1)
    runs = itertools.groupby(blank)

    for is_blank, run in runs:
        length = sum(1 for _ in run)
        if is_blank and length >= min_rows:
            gaps.append(Rows(y, y + length))
        y += length
    return gaps


def belongs(region: Region, panels: list[Panel], h: int) -> Panel:
    """The panel that holds most of the box of the region. A detected box can reach a few rows
    into a gap, so the panel around the edges of the box can be the wrong one."""
    y0, y1 = region.box[1] * h, region.box[3] * h
    return max(panels, key=lambda p: min(y1, p.bottom) - max(y0, p.top))  # rows of the box in p


def is_story(bubble: Region, ads: list[Region], title: str) -> bool:
    """A bubble that is neither ad text, nor touches ad text, nor is the title."""
    return (
        not AD_TEXT.search(bubble.text)
        and not any(overlap(bubble.box, ad.box) for ad in ads)
        and not same_words(bubble.text, title)
    )


def overlap(a: list[float], b: list[float]) -> bool:
    """Two boxes (left, top, right, bottom) overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def same_words(text: str, title: str) -> bool:
    """The text is the title (or most of it), whatever the punctuation and case."""
    a, b = (re.sub(r"[^a-z0-9]", "", s.lower()) for s in (text, title))
    return len(a) >= 6 and (a in b or b in a)


def page_image(ch: Chapter, index: int, urls: list[str] | None) -> Image.Image:
    """A page, from the download folder, or from the server's page URLs (urls) when the chapter
    is not downloaded."""
    if urls is None:
        folder = suwayomi.download_folder(ch)
        with Image.open(os.path.join(folder, suwayomi.page_files(folder)[index])) as img:
            return img.convert("RGB")
    return Image.open(io.BytesIO(suwayomi.fetch(urls[index]))).convert("RGB")


def preview(img: Image.Image, top: int, bottom: int, path: str) -> None:
    """Before (the cut tinted red) and after, side by side, with some rows around the cut."""
    w, h = img.size
    margin = int(0.5 * w)
    a, b = max(0, top - margin), min(h, bottom + margin)  # the rows shown: the cut, half a page width around

    # Before: the rows as they are, the cut tinted red.
    before = img.crop((0, a, w, b))
    tint = Image.new("RGB", (w, bottom - top), (255, 0, 0))
    before.paste(Image.blend(before.crop((0, top - a, w, bottom - a)), tint, 0.35), (0, top - a))
    # After: the rows above the cut, then those below it.
    after = Image.new("RGB", (w, max(1, (top - a) + (b - bottom))), "white")
    after.paste(img.crop((0, a, w, top)), (0, 0))
    after.paste(img.crop((0, bottom, w, b)), (0, top - a))
    # Side by side on grey, made small enough to look at.
    sheet = Image.new("RGB", (2 * w + w // 20, b - a), (128, 128, 128))
    sheet.paste(before, (0, 0))
    sheet.paste(after, (w + w // 20, 0))
    ImageDraw.Draw(sheet).line([(0, top - a), (w, top - a)], fill=(255, 0, 0), width=max(2, w // 300))
    sheet.thumbnail((900, 2400))
    sheet.save(path, quality=85)


def dry_run(chapter_id: int, folder: str | None = None) -> None:
    with open(os.path.join(OCR_DIR, f"{chapter_id}.json"), encoding="utf-8") as f:
        text = ChapterText.model_validate_json(f.read())
    ch = suwayomi.chapter(chapter_id)
    urls = None if ch.is_downloaded else suwayomi.page_list(chapter_id)
    print(f"{text.chapter} (id {chapter_id}), {len(text.pages)} pages")
    for page in text.pages:
        if not any(AD_TEXT.search(r.text) for r in page.regions):
            continue
        img = page_image(ch, page.index, urls)
        cuts, refused = find_cuts(img, page.regions, ch.manga.title)
        for top, bottom in cuts:
            whole = " (the whole page)" if (top, bottom) == (0, img.height) else ""
            print(f"  page {page.index}: cut rows {top}-{bottom} of {img.height}{whole}")
            if folder:
                preview(img, top, bottom, os.path.join(folder, f"{chapter_id}-p{page.index}-{top}.jpg"))
        for (top, bottom), reason in refused:
            print(f"  page {page.index}: NOT cut rows {top}-{bottom}: {reason}")
            if folder:
                name = f"{chapter_id}-p{page.index}-{top}-refused.jpg"
                preview(img, top, bottom, os.path.join(folder, name))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or not sys.argv[1].isdigit():
        sys.exit("usage: ads.py <chapterId> [preview folder]")
    out = sys.argv[2] if len(sys.argv) == 3 else None
    if out:
        os.makedirs(out, exist_ok=True)
    dry_run(int(sys.argv[1]), out)
