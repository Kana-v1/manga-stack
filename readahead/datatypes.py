"""The records that readahead uses, as structs. These are the answers of the GraphQL API of
the server. They are also the data that readahead keeps in its state files and sends over
HTTP.

Each class is a pydantic model. A pydantic model works like a Go struct with json tags:

- Each field has a declared type.
- `Chapter.model_validate(data)` makes a Chapter from decoded JSON. It fails at once if a field
  is missing or has the wrong type.
- `.model_dump_json()` makes JSON from the struct.

In Python the field names are snake_case (`ch.source_order`). In the JSON they are camelCase
(`sourceOrder`), as the server writes them. The reader and scripts/readahead.ts read these names.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Struct(BaseModel):
    """The base of every record below: snake_case fields, camelCase JSON keys."""

    model_config = ConfigDict(
        alias_generator=to_camel,  # source_order <-> "sourceOrder"
        validate_by_name=True,  # Chapter(source_order=1) works too, not only the JSON name
        serialize_by_alias=True,  # JSON written with the camelCase names
    )


# ---------------------------------------------------------------- the server (GraphQL)


class Nodes[T](Struct):
    """A list in a GraphQL answer, which wraps it: {"nodes": [...]}."""

    nodes: list[T]


class Source(Struct):
    display_name: str  # "Manga Demon (EN)"


class ChapterManga(Struct):
    title: str
    source: Source


class Chapter(Struct):
    """A chapter with the fields suwayomi.CHAPTER_FIELDS asks for."""

    id: int
    manga_id: int
    # Its place in the title, from the server: 1 for the first chapter, then 2, 3 and so on. It
    # gives the reading order. The chapter number does not always do this, because it comes from
    # the name and can be a part of a chapter ("Chapter 46.2").
    source_order: int
    name: str  # "Chapter 68"
    chapter_number: float
    scanlator: str | None
    is_read: bool
    is_downloaded: bool
    page_count: int
    manga: ChapterManga


class LibraryChapter(Struct):
    """A chapter as suwayomi.library() lists it, with fewer fields."""

    id: int
    name: str
    chapter_number: float
    source_order: int  # its place in the title: 1 for the first chapter (see Chapter)
    is_read: bool
    is_downloaded: bool


class LibraryManga(Struct):
    id: int
    title: str
    chapters: Nodes[LibraryChapter]


# ---------------------------------------------------------------- a pass


class UpscaleChapter(Chapter):
    """A chapter a pass keeps upscaled, and whether it is done (no page needs an upscale)."""

    done: bool


class PageHeader(Struct):
    """What the header of a page file shows, without the pixels (pages.py)."""

    width: int
    upscaled: bool  # the file has the UPSCALED comment: readahead upscaled this page


class TitlePlan(Struct):
    """What a pass would do for one title (planner.py)."""

    manga_id: int
    title: str
    last_read: LibraryChapter | None  # the furthest chapter read, or None before the first one
    upscale: list[UpscaleChapter]
    text: list[LibraryChapter]  # chapters whose text is to be read
    delete: list[LibraryChapter]  # read chapters whose download readahead made


class QueuedChapter(Struct):
    id: int
    chapter: str  # "<title> <chapter name>", for the log and the history


class DeletedDownload(QueuedChapter):
    deleted: bool  # False when the server still has it after the delete


class CleanupResult(Struct):
    downloads: list[DeletedDownload]
    forgotten: list[int]  # chapter ids no longer downloaded, so no longer readahead's


class TagChanges(Struct):
    tagged: list[int]  # chapter ids
    untagged: list[int]


class PassResult(Struct):
    """What a pass did before its chapters are worked through (background.run_pass)."""

    new_chapters: list[str] | None  # None when the library update failed
    cleanup: CleanupResult
    queued: list[QueuedChapter]  # to upscale
    text_queued: list[QueuedChapter]  # to read the text of
    tags: TagChanges


type Kind = Literal["upscale", "text"]  # what a job does
type State = Literal["idle", "queued", "downloading", "upscaling", "reading", "done", "error"]


class Job(Struct):
    state: State
    message: str | None = None  # when the state is "error"


class JobStatus(Job):
    """A chapter's job, as /api/chapter-status and /health answer."""

    chapter_id: int
    kind: Kind
    chapter: str | None = None  # "<title> <chapter name>", when the job knows it


# ---------------------------------------------------------------- the pass history

type Trigger = Literal["scheduled", "manual"]  # what started a pass
type Outcome = Literal["done", "failed", "skipped"]  # how it ended


class PassDetails(Struct):
    """What a pass did, by chapter names. Each field may be left out."""

    new_chapters: list[str] | None = None
    deleted: list[str] = []
    upscaled: list[str] = []
    text_read: list[str] = []
    failed: list[str] = []
    error: str | None = None


class HistoryEntry(PassDetails):
    """One line of the pass history (history.py)."""

    started: str  # local time, "2026-11-10 09:59:55"
    finished: str
    trigger: Trigger
    result: Outcome


class Health(Struct):
    """What /health answers."""

    ok: bool
    device: str  # "cuda" or "cpu"
    model: str  # the model's file name
    pass_running: bool
    last_pass: HistoryEntry | None
    next_pass_due: str  # a local time, "now", or "off"
    started: str  # when this readahead process started, as local time
    # The jobs that are queued, running, or failed since the start. A failed job stays here
    # until a later pass does it again.
    jobs: list[JobStatus]


# ---------------------------------------------------------------- a chapter's text (ocr.py)


class Region(Struct):
    """One piece of text on a page."""

    box: list[float]  # left, top, right, bottom, as fractions of the page's width and height
    kind: Literal["bubble", "free"]  # in a speech bubble, or outside one (captions, signs)
    text: str


class TextPage(Struct):
    index: int  # the page's number in the chapter, from 0
    regions: list[Region]
    width: int | None = None  # of the image the text was read from (None on a page in error)
    height: int | None = None
    panels: list[float] | None = None  # where panels start, as fractions of the page's height
    error: str | None = None  # the source could not deliver the page


class ChapterText(Struct):
    """The text of a chapter: OCR_DIR/<chapterId>.json, and what /api/ocr answers."""

    chapter_id: int
    manga_id: int
    source_order: int
    chapter: str  # "<title> <chapter name>"
    models: dict[str, str]  # "detector" and "reader": Hugging Face "repository@revision"
    created: str  # local time
    dropped: int  # regions read without a word in them
    missing_pages: list[int] = []  # the indexes of the pages in error (older files do not have it)
    pages: list[TextPage]
