#!/usr/bin/env python3
"""manga-stack readahead: prepares the next unread chapters of every library title before you
read them. It downloads them, reads their text (OCR), cuts the ads and upscales the pages 2x.

GET  /api/plan                         dry run of a pass: what to upscale, what to delete
POST /api/pass                         a pass now: library update, delete those downloads,
                                       queue those chapters, fix the tags of the chapter list
GET  /api/chapter-status?chapterId=N[&kind=text]  the job of a chapter: idle, queued, ..., done or error
GET  /api/ocr?chapterId=N              the recognised text of a chapter, for the bubble boxes of the reader
GET  /health                           the model, and the last and next pass

Passes also run every READAHEAD_INTERVAL_MINUTES. Each pass adds a line to the pass history.

Threads:
- the HTTP server: one thread per request
- the scheduler (background.py)
- the job worker, which downloads, upscales and reads text (jobs.py)
- one thread per pass, which waits for the chapters of the pass

The modules in this folder:
  background.py       the pass, and the scheduler that starts one every INTERVAL_MINUTES
  history.py          one line per pass, kept across restarts
  planner.py          what to upscale ahead of the reader, and which downloads to delete
  jobs.py             the queue of jobs: download and upscale a chapter, or read its text
  cleanup.py          delete the downloads of read chapters
  download_record.py  the chapters whose download readahead made (a state file)
  tags.py             the "upscaled" tag that the chapter list shows (chapter meta on the server)
  suwayomi.py         the server: GraphQL, downloads, download folders
  pages.py            page files, and the model that upscales them on the GPU
  ads.py              the ad panels of scanlators in the pages of a chapter, found through its text
  ocr.py              the text of speech bubbles and captions (scripts/readahead.ts ocr ID)
  config.py           settings, from stack.conf
  datatypes.py        the records that it reads and writes, as structs

scripts/readahead.ts is the command line for it: start, stop, status, plan, pass, history, ocr.
"""

import json
import logging
import os
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from pydantic_core import to_jsonable_python

import background
import history
import jobs
import ocr
import pages
import planner
from config import INTERVAL_MINUTES, MODEL_PATH, PORT, SERVER_URL
from datatypes import Health, Kind

log = logging.getLogger("readahead")
# The reader runs on the origin of the server. Only the reader can read /api/ocr from the browser.
READER_ORIGINS = {f"http://{host}:{urlsplit(SERVER_URL).port}" for host in ("127.0.0.1", "localhost")}


def health() -> Health:
    last = history.recent(1)
    if not INTERVAL_MINUTES:
        next_pass = "off"
    else:
        due = background.next_due()
        next_pass = history.stamp(due) if due else "now"
    return Health(
        ok=True,
        device=str(pages.device),
        model=os.path.basename(MODEL_PATH),
        pass_running=background.running.locked(),
        last_pass=last[0] if last else None,
        next_pass_due=next_pass,
    )


class Handler(BaseHTTPRequestHandler):
    """One HTTP request. do_GET and do_POST pick the function that answers the path (see the
    list at the top of this file). answer() runs it and replies with its result as JSON, or with
    its error."""

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/health":
            self.answer(health)
        elif url.path == "/api/plan":
            self.answer(planner.plan)
        elif url.path == "/api/chapter-status":
            query = parse_qs(url.query)
            kind: Kind = "text" if query.get("kind") == ["text"] else "upscale"
            self.answer(lambda: jobs.status(int(query["chapterId"][0]), kind))
        elif url.path == "/api/ocr":
            self.chapter_text(url.query)
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/api/pass":
            self.answer(lambda: background.start_pass("manual"))
        else:
            self.reply(404, {"error": "not found"})

    def answer(self, handler: Callable[[], object]) -> None:
        """Reply with what the handler returns, or with its error."""
        try:
            self.reply(200, handler())
        except Exception as exc:
            log.exception("%s failed", self.path)
            self.reply(500, {"state": "error", "message": str(exc)})

    def chapter_text(self, query: str) -> None:
        try:
            text = ocr.saved(int(parse_qs(query)["chapterId"][0]))
        except (KeyError, ValueError):
            return self.reply(400, {"error": "chapterId missing"}, cors=True)
        self.reply(200 if text else 404, text or {"error": "no text for this chapter"}, cors=True)

    def reply(self, code: int, obj: object, cors: bool = False) -> None:
        # a struct (datatypes.py) becomes its JSON, with the camelCase names
        body = json.dumps(to_jsonable_python(obj, by_alias=True), ensure_ascii=False).encode()
        self.send_response(code)
        if cors and self.headers.get("Origin") in READER_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # no access log
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    model = os.path.basename(MODEL_PATH)
    log.info("model %s on %s (%s), %sx, port %s", model, pages.device, pages.dtype, pages.model.scale, PORT)
    threading.Thread(target=jobs.worker, daemon=True).start()
    if INTERVAL_MINUTES:
        threading.Thread(target=background.scheduler, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
