"""Jobs, one for each chapter and kind:

- upscale: download the chapter if necessary, and read its text if it is not read (ocr.py).
  Then cut the ads out of its pages (ads.py) and upscale the pages in place.
- text: read the text of its speech bubbles (ocr.py).

A pass queues the jobs, and one thread does them in order. So only one job at a time downloads,
upscales or reads. The source allows approximately 2 requests per second, and the GPU takes one
page at a time. When the queue is empty, the text models give their GPU memory back.

The state of a job: idle -> queued -> (downloading ->) upscaling or reading -> done, or error
with a message. The states are kept in memory only. After a restart, every chapter is idle
again, and the next pass queues the work that is not done.
"""

import logging
import os
import queue
import threading
from typing import assert_never

import ads
import download_record
import ocr
import pages
import suwayomi
import tags
from datatypes import ChapterText, Job, JobStatus, Kind, State

log = logging.getLogger("readahead")
RUNNING: tuple[State, ...] = ("queued", "downloading", "upscaling", "reading")  # not finished yet
jobs: dict[tuple[Kind, int], Job] = {}  # (kind, chapter id) -> its job
work: queue.Queue[tuple[Kind, int]] = queue.Queue()  # (kind, chapter id), in the order queued
lock = threading.Lock()  # passes queue jobs from the threads of the HTTP server and the scheduler


# ---------------------------------------------------------------- the queue


def status(chapter_id: int, kind: Kind = "upscale") -> JobStatus:
    job = jobs.get((kind, chapter_id), Job(state="idle"))
    return JobStatus(chapter_id=chapter_id, kind=kind, state=job.state, message=job.message)


def running(chapter_id: int, kind: Kind = "upscale") -> bool:
    return status(chapter_id, kind).state in RUNNING


def enqueue(chapter_id: int, kind: Kind = "upscale") -> None:
    """Queue a job for the chapter, unless one of that kind is queued or running."""
    # The lock makes the check and the queueing one step. Without it, two threads could both
    # find the chapter not running, and both queue it. The queue itself needs no lock.
    with lock:
        if not running(chapter_id, kind):
            jobs[(kind, chapter_id)] = Job(state="queued")
            work.put((kind, chapter_id))


def worker() -> None:
    """Run the queued jobs one at a time, forever."""
    while True:
        # get() waits until a job is queued. The thread sleeps while it waits, and does not poll.
        # It needs no lock: queue.Queue is safe across threads, and this is the only reader.
        kind, chapter_id = work.get()
        match kind:  # the kinds are in Kind (datatypes.py)
            case "upscale":
                upscale(chapter_id)
            case "text":
                read_text(chapter_id)
            case _:
                assert_never(kind)  # mypy fails here if a kind has no case
        # Give back the GPU memory of the text models when no job waits. This occurs once, after
        # the last queued job. When the models are not loaded, unload() does nothing.
        if work.empty():
            ocr.unload()


# ---------------------------------------------------------------- the upscale job


def upscale(chapter_id: int) -> None:
    """Download the chapter if necessary, and read its text if it is not read. Then cut the ads
    out of its pages and upscale them. The state of the job shows how far it got."""
    key: tuple[Kind, int] = ("upscale", chapter_id)
    try:
        # Get the chapter as it is now, not as it was when it was queued. Someone may have
        # downloaded it since then.
        ch = suwayomi.chapter(chapter_id)
        name = f"{ch.manga.title} {ch.name}"

        # 1. Download the chapter, unless the server has it.
        if not ch.is_downloaded:
            jobs[key] = Job(state="downloading")
            log.info("chapter %s (%s): downloading", chapter_id, name)
            download_record.add(
                chapter_id
            )  # record it first, so that a crash cannot leave a download unrecorded
            suwayomi.download(chapter_id)
        folder = suwayomi.download_folder(ch)
        files = [os.path.join(folder, file) for file in suwayomi.page_files(folder)]

        # 2. Get its text, and read it now if it is not read. The text shows where the ads are.
        text = chapter_text(chapter_id, key, len(files))

        # 3. For each page: cut the ads out, then upscale the page.
        jobs[key] = Job(state="upscaling")
        log.info("chapter %s (%s): upscaling %d pages", chapter_id, name, len(files))
        cut, upscaled = process_pages(files, text, ch.manga.title)

        # 4. Put the "HD" mark on the chapter in the chapter list, if a page was upscaled. A
        # chapter whose original pages are wide enough gets no mark.
        if upscaled:
            tags.tag([chapter_id])
        jobs[key] = Job(state="done")
        log.info("chapter %s: done, %d ads cut, %d/%d pages upscaled", chapter_id, cut, upscaled, len(files))
    except Exception as exc:
        log.exception("chapter %s failed", chapter_id)
        jobs[key] = Job(state="error", message=str(exc))


def process_pages(files: list[str], text: ChapterText | None, title: str) -> tuple[int, int]:
    """Cut the ads out of each page file and upscale it (pages.process). When a page loses rows,
    its text boxes move up with them, and the text is saved again. Returns how many ads were cut
    and how many pages were upscaled."""
    cut = upscaled = 0
    for i, path in enumerate(files):
        page_text = text.pages[i] if text else None
        cuts, was_upscaled = pages.process(path, page_text, title)
        if cuts and page_text:
            ads.shift(page_text, cuts)
        cut += len(cuts)
        upscaled += was_upscaled
    if cut and text:
        ocr.save(text)
    return cut, upscaled


def chapter_text(chapter_id: int, key: tuple[Kind, int], page_count: int) -> ChapterText | None:
    """The recognised text of the chapter, read now if it is not read. The text shows where the
    ads are. None when the read fails: then the pages are upscaled with their ads. Also None
    when the text is from pages that are not the downloaded ones."""
    if not ocr.has_text(chapter_id):
        jobs[key] = Job(state="reading")
        try:
            ocr.read_chapter(chapter_id)
        except Exception:
            log.exception("chapter %s: reading its text failed; its ads stay", chapter_id)
            return None
    text = ocr.saved(chapter_id)
    return text if text and len(text.pages) == page_count else None


# ---------------------------------------------------------------- the text job


def read_text(chapter_id: int) -> None:
    """Read the text of the chapter (ocr.py), unless its upscale job read it already."""
    key: tuple[Kind, int] = ("text", chapter_id)
    try:
        if ocr.has_text(chapter_id):  # its upscale job read it already
            jobs[key] = Job(state="done")
            return

        jobs[key] = Job(state="reading")
        ocr.read_chapter(chapter_id)  # writes its own summary to the log
        jobs[key] = Job(state="done")

    except Exception as exc:
        log.exception("chapter %s: reading its text failed", chapter_id)
        jobs[key] = Job(state="error", message=str(exc))
