"""Delete the downloads that readahead made, after their chapter is read. When someone opens
such a chapter again, its original pages come from the source again, as before the upscale."""

import logging

import download_record
import jobs
import suwayomi
from datatypes import CleanupResult, DeletedDownload, QueuedChapter, TitlePlan

log = logging.getLogger("readahead")


def run(plan: list[TitlePlan]) -> CleanupResult:
    """Delete the downloads that the plan (planner.plan()) marks for deletion. Then forget the
    recorded chapters whose download is gone (download_record.py). Returns what happened."""
    # 1. Find the downloads to delete. If someone reads a chapter while its job runs, the chapter
    # waits for a later pass.
    to_delete = [
        QueuedChapter(id=c.id, chapter=f"{t.title} {c.name}")
        for t in plan
        for c in t.delete
        if not jobs.running(c.id)
    ]

    # 2. Delete them. Then ask the server which downloads are gone.
    if to_delete:
        suwayomi.delete_downloads([d.id for d in to_delete])
    downloaded = suwayomi.downloaded_ids()
    downloads = [
        DeletedDownload(id=d.id, chapter=d.chapter, deleted=d.id not in downloaded) for d in to_delete
    ]
    for d in downloads:
        outcome = "deleted" if d.deleted else "NOT deleted"
        log.info("chapter %s (%s): download %s", d.id, d.chapter, outcome)

    # 3. Forget the chapters whose download is gone (deleted here, or by hand). Keep a chapter
    # whose job runs: its download may have started and not finished.
    forgotten = download_record.keep_only(lambda cid: cid in downloaded or jobs.running(cid))
    return CleanupResult(downloads=downloads, forgotten=sorted(forgotten))
