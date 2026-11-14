"""The pass history: one JSON line for each pass, in HISTORY_FILE. The file stays across
restarts, so days later it shows when passes ran and what each pass did (`scripts/readahead.ts
history`). The scheduler also reads it: the next pass is due INTERVAL_MINUTES after the last
pass started.

A line is a HistoryEntry (datatypes.py): when the pass started and finished, what started it,
how it ended, and what it did.
"""

import datetime
import os
import threading
import time

from config import HISTORY_FILE
from datatypes import HistoryEntry, Outcome, PassDetails, Trigger

lock = threading.Lock()  # a pass that ends and a pass that is skipped can write at the same time


def add(started: float, trigger: Trigger, result: Outcome, details: PassDetails | None = None) -> None:
    """Write the line of a pass. `started` is in seconds since 1970 (time.time())."""
    entry = HistoryEntry(
        started=stamp(started),
        finished=stamp(time.time()),
        trigger=trigger,
        result=result,
        **dict(details or PassDetails()),  # each field of the details, as a separate argument
    )
    with lock:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")


def recent(n: int | None = None) -> list[HistoryEntry]:
    """The last n passes (all when n is None), oldest first."""
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            entries = [HistoryEntry.model_validate_json(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
    return entries[-n:] if n else entries


def last_start() -> float | None:
    """When the latest pass started, in seconds since the epoch. None before the first pass. A
    pass writes its line when it ends, so the latest start is not always on the last line."""
    starts = [datetime.datetime.fromisoformat(e.started).timestamp() for e in recent(10)]
    return max(starts, default=None)


def stamp(seconds: float) -> str:
    """Seconds since 1970 as local time: "2026-11-10 09:59:55"."""
    return datetime.datetime.fromtimestamp(seconds).isoformat(sep=" ", timespec="seconds")
