"""Passes keep the next unread chapters upscaled and their text read. A pass does these steps:

1. It asks the server to look for new chapters.
2. It deletes the downloads that readahead made of chapters that are now read.
3. It queues the chapters that the plan picks: first those to upscale, then those to read.
4. It makes the "upscaled" tags of the chapter list agree with the files.

A pass starts every INTERVAL_MINUTES (the scheduler), or when you ask for one
(`scripts/readahead.ts pass`). Only one pass runs at a time. A pass continues until its last
chapter is done. A pass that is due before then is skipped. Each pass writes a line to the pass
history (history.py).

A pass runs in two halves, on two threads:
  start_pass  (the thread of the caller: the scheduler, or the HTTP request of a manual pass)
              updates the library, cleans up, queues the chapters and fixes the tags. It returns
              what it queued, so that a manual pass can show it and follow the chapters.
  finish      (a thread of its own) waits until the queued chapters are done. Then it writes the
              history line.
The `running` lock covers both halves: start_pass takes it, and finish releases it. (A plain
threading.Lock allows a different thread to release it.)
"""

import logging
import threading
import time

import cleanup
import history
import jobs
import planner
import suwayomi
import tags
from config import INTERVAL_MINUTES
from datatypes import (
    Kind,
    LibraryChapter,
    PassDetails,
    PassResult,
    QueuedChapter,
    TitlePlan,
    Trigger,
    UpscaleChapter,
)

log = logging.getLogger("readahead")
running = threading.Lock()  # held from the start of a pass until its last chapter is done
# When the latest pass started. A pass gets its history line only when it ends, which can be an
# hour later. Without this time, the scheduler would start the next pass while one runs.
last_started = 0.0


# ---------------------------------------------------------------- when passes run


def scheduler() -> None:
    """Start a pass when one is due and the server answers. A pass is due INTERVAL_MINUTES after
    the last one started. The start time comes from the history, so the interval continues
    across restarts."""
    while True:
        time.sleep(60)
        try:
            if time.time() >= next_due() and suwayomi.answers():
                start_pass("scheduled")
        except Exception:
            log.exception("scheduled pass failed")


def next_due() -> float:
    """When the next scheduled pass is due, in seconds since the epoch. Before the first pass, 0
    (now). The history covers the passes before a restart, and last_started covers the pass that
    runs."""
    last = max(history.last_start() or 0, last_started)
    return last + INTERVAL_MINUTES * 60 if last else 0


# ---------------------------------------------------------------- a pass


def start_pass(trigger: Trigger) -> PassResult | None:
    """Start a pass. If a pass runs already, record this one as skipped. Returns what the pass
    did up to the queueing of its chapters, or None when it was skipped."""
    global last_started
    started = last_started = time.time()

    # One pass at a time. A pass that is due while another runs is recorded as skipped.
    if not running.acquire(blocking=False):
        log.info("pass: skipped, the previous one is still running")
        history.add(started, trigger, "skipped", PassDetails(error="the previous pass is still running"))
        return None

    # The first half runs here, up to the queueing of the chapters.
    try:
        result = run_pass()
    except Exception as exc:
        running.release()  # no finish() to release it
        history.add(started, trigger, "failed", PassDetails(error=str(exc)))
        raise

    # The second half runs in a thread of its own. From now on, that thread owns the lock and
    # releases it.
    threading.Thread(target=finish, args=(started, trigger, result), daemon=True).start()
    return result


def run_pass() -> PassResult:
    """The first half of a pass: update the library, clean up, queue the chapters and fix the
    tags. Returns what it did. Then the queue works through the chapters one at a time."""
    log.info("pass: start")

    # 1. Have the server look for new chapters.
    new = update_library()

    # 2. Find what to do for each title (planner.py). Delete the downloads of chapters read since.
    plan = planner.plan()
    deleted = cleanup.run(plan)

    # 3. Queue the chapters to upscale (unless they are done), then those to read the text of.
    queued = [job(t, c) for t in plan for c in t.upscale if not c.done]
    text = [job(t, c) for t in plan for c in t.text]
    for q in queued:
        jobs.enqueue(q.id, "upscale", q.chapter)
    for q in text:
        jobs.enqueue(q.id, "text", q.chapter)
    log.info("pass: %d chapters queued to upscale, %d to read the text of", len(queued), len(text))

    # 4. Make the "HD" marks of the chapter list agree with the files. A chapter gets a mark only
    # when no page of it needs an upscale (pages.is_upscaled). So the chapters queued above get no
    # mark here. Each one gets its mark from its job, when the job ends (jobs.upscale). This step
    # repairs the marks that are wrong, for example of a download deleted in step 2 or by hand.
    changed = tags.sync()
    log.info("pass: tags %s", changed)
    return PassResult(new_chapters=new, cleanup=deleted, queued=queued, text_queued=text, tags=changed)


def finish(started: float, trigger: Trigger, result: PassResult) -> None:
    """The second half of a pass: wait until its chapters are done, then write its history line.
    Releases the pass lock in all cases."""
    try:
        # The pass's jobs: the chapters to upscale and those to read the text of.
        queued: list[tuple[QueuedChapter, Kind]] = []
        for q in result.queued:
            queued.append((q, "upscale"))
        for q in result.text_queued:
            queued.append((q, "text"))

        # 1. Wait until none of them is queued or running any more.
        while any(jobs.running(q.id, kind) for q, kind in queued):
            time.sleep(5)

        # 2. Sort the chapter names by how each job ended.
        upscaled: list[str] = []
        text_read: list[str] = []
        failed: list[str] = []
        for q, kind in queued:
            if jobs.status(q.id, kind).state != "done":
                failed.append(f"{q.chapter} ({kind})")
            elif kind == "upscale":
                upscaled.append(q.chapter)
            else:
                text_read.append(q.chapter)

        # 3. Write the history line.
        new = result.new_chapters
        details = PassDetails(
            new_chapters=new,
            deleted=[d.chapter for d in result.cleanup.downloads if d.deleted],
            upscaled=upscaled,
            text_read=text_read,
            failed=failed,
            error="the library update failed" if new is None else None,
        )
        history.add(started, trigger, "failed" if failed or new is None else "done", details)
        log.info(
            "pass: finished, %d upscaled, text of %d read, %d failed",
            len(upscaled),
            len(text_read),
            len(failed),
        )
    finally:
        running.release()


# ---------------------------------------------------------------- helpers


def job(title: TitlePlan, chapter: LibraryChapter | UpscaleChapter) -> QueuedChapter:
    return QueuedChapter(id=chapter.id, chapter=f"{title.title} {chapter.name}")


def update_library() -> list[str] | None:
    """Have the server look for new chapters. Returns the new ones, or None when the update
    failed. Then the pass continues with the chapters that it knows."""
    before = chapter_names()
    try:
        suwayomi.update_library()
    except Exception:
        log.exception("pass: the library update failed")
        return None
    new = [name for cid, name in chapter_names().items() if cid not in before]
    log.info("pass: library updated, %d new chapters %s", len(new), new)
    return new


def chapter_names() -> dict[int, str]:
    """Chapter id -> "<title> <chapter name>", for every chapter in the library."""
    return {c.id: f"{m.title} {c.name}" for m in suwayomi.library() for c in m.chapters.nodes}
