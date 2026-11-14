"""The download record: the chapters whose download readahead made. Readahead deletes only these
downloads. A download that a person made is not in the record, so readahead never deletes it.

DOWNLOAD_RECORD_FILE keeps the record as a JSON list of chapter ids, so the record stays across
restarts. A chapter is recorded before its download starts. It is forgotten when its download is
gone.
"""

import json
import os
import threading
from collections.abc import Callable

from config import DOWNLOAD_RECORD_FILE

lock = threading.Lock()  # the jobs and the cleanup change the file from different threads


def load() -> set[int]:
    try:
        with open(DOWNLOAD_RECORD_FILE) as f:
            ids: list[int] = json.load(f)
            return set(ids)
    except FileNotFoundError:
        return set()


def add(chapter_id: int) -> None:
    with lock:
        save(load() | {chapter_id})


def keep_only(keep: Callable[[int], bool]) -> set[int]:
    """Forget each chapter for which keep(chapter_id) is false. Returns the forgotten chapters."""
    with lock:
        chapters_ids = load()
        gone = {cid for cid in chapters_ids if not keep(cid)}
        if gone:
            save(chapters_ids - gone)
        return gone


def save(chapter_ids: set[int]) -> None:
    tmp = DOWNLOAD_RECORD_FILE + ".tmp"
    os.makedirs(os.path.dirname(DOWNLOAD_RECORD_FILE), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(sorted(chapter_ids), f)
    os.replace(tmp, DOWNLOAD_RECORD_FILE)  # atomic: a reader never gets a half-written file
