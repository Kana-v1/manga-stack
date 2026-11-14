"""The Suwayomi server: GraphQL calls, chapter downloads, and where the downloads are on disk.

All access goes through the GraphQL API. Nothing here touches the database. gql() returns the
decoded JSON of an answer. Each function reads that JSON into a struct (from datatypes.py, or an
answer struct below). The struct fails at once if the server sent something different.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping

from config import DATA_DIR, SERVER_URL
from datatypes import Chapter, LibraryManga, Nodes, Struct

PAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
CHAPTER_FIELDS = (
    "id mangaId sourceOrder name chapterNumber scanlator isRead isDownloaded pageCount"
    " manga { title source { displayName } }"
)


class GqlError(RuntimeError):
    """The server answered with GraphQL errors. The message is the message of the first error."""


class ErrorMessage(Struct):
    message: str = "GraphQL error"


class GqlAnswer(Struct):
    """The form of every GraphQL answer: the data, or the errors."""

    data: object = None
    errors: list[ErrorMessage] | None = None


def gql(query: str, variables: Mapping[str, object] | None = None, timeout: float = 30) -> object:
    """Run a query or mutation and return the decoded JSON of its data. Raises GqlError when the
    answer has GraphQL errors, and OSError when the server does not answer."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(
        f"{SERVER_URL}/api/graphql", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw: bytes = response.read()
    except urllib.error.HTTPError as err:  # an answer with GraphQL errors can have an HTTP error status
        raw = err.read()
    try:
        answer = GqlAnswer.model_validate_json(raw)
    except ValueError as exc:  # not JSON, or not a GraphQL answer
        raise OSError(f"no GraphQL answer from {SERVER_URL}/api/graphql: {raw[:200]!r}") from exc
    if answer.errors:
        raise GqlError(answer.errors[0].message)
    return answer.data


def answers() -> bool:
    try:
        gql("{ __typename }", timeout=5)
        return True
    except OSError:
        return False


class ChapterAnswer(Struct):
    chapter: Chapter


def chapter(chapter_id: int) -> Chapter:
    query = f"query($id: Int!) {{ chapter(id: $id) {{ {CHAPTER_FIELDS} }} }}"
    return ChapterAnswer.model_validate(gql(query, {"id": chapter_id})).chapter


class LibraryAnswer(Struct):
    mangas: Nodes[LibraryManga]


def library() -> list[LibraryManga]:
    """The library titles, each with all its chapters."""
    query = (
        "{ mangas(condition: {inLibrary: true}) { nodes { id title"
        " chapters { nodes { id name chapterNumber sourceOrder isRead isDownloaded } } } } }"
    )
    return LibraryAnswer.model_validate(gql(query)).mangas.nodes


class Timestamp(Struct):
    timestamp: str  # milliseconds since 1970, as a string


class JobsInfo(Struct):
    is_running: bool


class UpdateStatus(Struct):
    jobs_info: JobsInfo


class UpdateAnswer(Struct):
    last_update_timestamp: Timestamp
    library_update_status: UpdateStatus


def update_library() -> None:
    """Have the server look for new chapters of the library titles. Return when it is done. The
    server skips the titles that its settings exclude (never started, completed)."""
    started = time.time() * 1000
    gql("mutation { updateLibrary(input: {}) { clientMutationId } }")
    # For a short time, the status still shows the previous update as finished. The server sets
    # lastUpdateTimestamp when an update starts. So our update is done when that time is after
    # our start and no update runs.
    query = "{ lastUpdateTimestamp { timestamp } libraryUpdateStatus { jobsInfo { isRunning } } }"
    deadline = time.monotonic() + 10 * 60
    while time.monotonic() < deadline:
        time.sleep(1)
        status = UpdateAnswer.model_validate(gql(query))
        stamp = int(status.last_update_timestamp.timestamp)
        if stamp >= started and not status.library_update_status.jobs_info.is_running:
            return
    raise RuntimeError("the library update did not finish within 10 minutes")


def downloaded_ids() -> set[int]:
    return {c.id for c in downloaded_chapters()}


class ChaptersAnswer(Struct):
    chapters: Nodes[Chapter]


def downloaded_chapters() -> list[Chapter]:
    query = f"{{ chapters(filter: {{isDownloaded: {{equalTo: true}}}}) {{ nodes {{ {CHAPTER_FIELDS} }} }} }}"
    return ChaptersAnswer.model_validate(gql(query)).chapters.nodes


class MetaKey(Struct):
    key: str


class ChapterMeta(Struct):
    id: int
    meta: list[MetaKey]


class ChapterMetaAnswer(Struct):
    chapters: Nodes[ChapterMeta]


def chapters_with_meta(key: str) -> set[int]:
    """The ids of the chapters that have this meta key. The API cannot filter by meta, so this
    gets all chapters."""
    answer = ChapterMetaAnswer.model_validate(gql("{ chapters { nodes { id meta { key } } } }"))
    return {c.id for c in answer.chapters.nodes if any(m.key == key for m in c.meta)}


def set_chapter_meta(chapter_ids: list[int], key: str, value: str) -> None:
    query = (
        "mutation($ids: [Int!]!, $key: String!, $value: String!) { setChapterMetas(input:"
        " {items: [{chapterIds: $ids, metas: [{key: $key, value: $value}]}]}) { clientMutationId } }"
    )
    gql(query, {"ids": chapter_ids, "key": key, "value": value})


def delete_chapter_meta(chapter_ids: list[int], key: str) -> None:
    query = (
        "mutation($ids: [Int!]!, $key: String!) { deleteChapterMetas(input:"
        " {items: [{chapterIds: $ids, keys: [$key]}]}) { clientMutationId } }"
    )
    gql(query, {"ids": chapter_ids, "key": key})


def delete_downloads(chapter_ids: list[int]) -> None:
    """Delete the downloads of the chapters. When a chapter is read again, its pages come from
    the source."""
    query = "mutation($ids: [Int!]!) { deleteDownloadedChapters(input: {ids: $ids}) { clientMutationId } }"
    gql(query, {"ids": chapter_ids})


class ChapterId(Struct):
    id: int


class QueueItem(Struct):
    chapter: ChapterId
    state: str  # "QUEUED", "DOWNLOADING", "FINISHED", "ERROR"


class DownloadQueue(Struct):
    queue: list[QueueItem]


class DownloadStatusAnswer(Struct):
    download_status: DownloadQueue


def download(chapter_id: int) -> None:
    """Have the server download a chapter. Return when it is on disk."""
    # 1. Queue it. After it queues a download, the server waits up to 30 s for a progress event.
    # A chapter in its cache finishes before it sends one. So the timeout is short, and a timeout
    # is not a failure: the chapter is queued in both cases.
    try:
        gql(
            "mutation($id: Int!) { enqueueChapterDownload(input: {id: $id}) { clientMutationId } }",
            {"id": chapter_id},
            timeout=3,
        )
    except OSError:
        pass

    # 2. Wait until it is on disk, or until the server reports that the download failed.
    deadline = time.monotonic() + 30 * 60
    while time.monotonic() < deadline:
        if chapter(chapter_id).is_downloaded:
            return
        answer = gql("{ downloadStatus { queue { chapter { id } state } } }")
        queue = DownloadStatusAnswer.model_validate(answer).download_status.queue
        if any(q.chapter.id == chapter_id and q.state == "ERROR" for q in queue):
            raise RuntimeError("the server could not download the chapter (see its log)")
        time.sleep(1)
    raise RuntimeError("the download did not finish within 30 minutes")


class PageList(Struct):
    pages: list[str]


class PageListAnswer(Struct):
    fetch_chapter_pages: PageList


def page_list(chapter_id: int) -> list[str]:
    """The URLs of the pages of the chapter on the server. For a chapter that nobody opened, the
    server first gets the page list from the source. This marks no chapter as read."""
    query = "mutation($id: Int!) { fetchChapterPages(input: {chapterId: $id}) { pages } }"
    answer = gql(query, {"id": chapter_id}, timeout=120)
    return PageListAnswer.model_validate(answer).fetch_chapter_pages.pages


def fetch(path: str, timeout: float = 120) -> bytes:
    """The bytes at a URL path of the server, for example a page from page_list. Raises OSError
    when it fails (an HTTPError is also an OSError)."""
    with urllib.request.urlopen(SERVER_URL + path, timeout=timeout) as response:
        page: bytes = response.read()
        return page


class DownloadSettings(Struct):
    downloads_path: str  # "" means <data dir>/downloads
    download_as_cbz: bool


class SettingsAnswer(Struct):
    settings: DownloadSettings


def download_folder(ch: Chapter) -> str:
    """<downloads>/mangas/<source>/<title>/<chapter>, with the names that the server gives the
    folders."""
    answer = gql("{ settings { downloadsPath downloadAsCbz } }")
    settings = SettingsAnswer.model_validate(answer).settings
    if settings.download_as_cbz:
        raise RuntimeError("downloads are stored as CBZ; only folder downloads are supported")
    root = settings.downloads_path or os.path.join(DATA_DIR, "downloads")
    name = f"{ch.scanlator}_{ch.name}" if ch.scanlator else ch.name
    source, title = ch.manga.source.display_name, ch.manga.title
    folder = os.path.join(root, "mangas", safe_name(source), safe_name(title), safe_name(name))
    if not os.path.isdir(folder):
        raise RuntimeError(f"download folder not found: {folder}")
    return folder


def page_files(folder: str) -> list[str]:
    """The page files in the download folder of a chapter, in page order."""
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(PAGE_EXTENSIONS))


def safe_name(name: str) -> str:
    """A folder name, made the same way as SafePath.buildValidFilename of the server makes it.
    Then readahead finds the folders that the server downloads into. If a server upgrade
    changes these rules, jobs fail with "download folder not found"."""
    name = name.strip(". ") or "(invalid)"  # no dots or spaces at either end
    # control characters, and the characters that Windows does not allow in file names, become "_"
    name = "".join("_" if ord(c) <= 0x1F or c in '"*/:<>?\\|\x7f' else c for c in name)
    # Make the name at most 240 UTF-16 units (the string length in Kotlin) and 240 UTF-8 bytes
    # (the limit of the file system is 255). A character above U+FFFF, for example an emoji, is
    # 2 UTF-16 units.
    out, units, size = "", 0, 0
    for c in name:
        units, size = units + (2 if ord(c) > 0xFFFF else 1), size + len(c.encode())
        if units > 240 or size > 240:
            break
        out += c
    return out
