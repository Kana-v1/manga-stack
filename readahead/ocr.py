#!/usr/bin/env python3
"""Text recognition: the text of the speech bubbles and captions of a chapter, and where it is.

    scripts/readahead.ts ocr <chapterId>    read one chapter now

Two models from Hugging Face do the work. stack.conf pins them, and transformers loads them when
text is first read:

- A comic text detector (RT-DETR-v2) finds text in bubbles and outside them. It was trained on
  manga, webtoons, manhua and Western comics. Tall strips go through it in tiles that overlap,
  because it was trained on images of that shape.
- PaddleOCR-VL reads each region. transformers has its own code for this model, so only the
  weights come from the model's repository, no code.

A result without a word in it is dropped, because the reader invents text for regions that hold
none. Cyrillic and Greek letters that look like Latin ones become Latin, and the text becomes
lowercase.

Output: OCR_DIR/<chapterId>.json. A box is fractions of the width and height of its page, so it
fits the original page and the upscaled page. Each page also lists where its panels start
("panels", fractions of its height). With the bubbles, these are the stops of the click-scroll
of the reader. Pages come from the download folder when the chapter is downloaded. Otherwise
they come through the server, in memory, and no chapter is marked read.
"""

import datetime
import gc
import io
import logging
import os
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

import torch
import torchvision
from PIL import Image

import ads
import suwayomi
from config import OCR_DETECTOR, OCR_DIR, OCR_READER
from datatypes import Chapter, ChapterText, Region, TextPage

if TYPE_CHECKING:  # for the type checker only: load() imports transformers when it is needed
    import transformers

log = logging.getLogger("readahead")
Image.MAX_IMAGE_PIXELS = 400_000_000  # webtoon strips are tall

THRESHOLD = 0.35  # detector confidence
TILE, OVERLAP = 1.5, 0.5  # tile height and overlap between tiles, in page widths (see detect)
PAD = 0.0075  # margin around a region, in page widths: the reader gets whole letters
# The text classes of the detector. Class 0 is the outline of a bubble.
type TextKind = Literal["bubble", "free"]  # in a speech bubble, or outside one
KINDS: dict[int, TextKind] = {1: "bubble", 2: "free"}
type Box = tuple[float, float, float, float]  # left, top, right, bottom, in pixels
# The reader sometimes returns Cyrillic or Greek letters that look like Latin ones (a Cyrillic
# "ОК" for "OK"). A dictionary or a translator then cannot find the copied text.
LOOKALIKES = str.maketrans("АВЕКМНОРСТХаеорсухІіЈјΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEKMHOPCTXaeopcyxIiJjABEZHIKMNOPTYX")
device = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class Models:
    """The two models, and what turns an image into each one's input."""

    detector_input: "transformers.RTDetrImageProcessor"
    detector: "transformers.RTDetrV2ForObjectDetection"  # finds where the text is on a page
    reader_input: "transformers.PaddleOCRVLProcessor"
    reader: "transformers.PaddleOCRVLForConditionalGeneration"  # reads the text in one region


models: Models | None = None  # None until load(), and again after unload()


def load() -> Models:
    """The models, loaded (~2.5 GB of GPU memory) unless they are already."""
    global models

    if models:
        return models

    import transformers  # slow to import, so it is imported only when text is read

    transformers.logging.set_verbosity_error()
    transformers.logging.disable_progress_bar()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the hub's request log

    detector, detector_revision = OCR_DETECTOR.split("@")
    reader, reader_revision = OCR_READER.split("@")

    # transformers wraps the .to() of a model in a decorator that hides its real arguments. That
    # is why two calls have "type: ignore": the call is correct, the declaration of the library
    # is not.
    models = Models(
        # AutoImageProcessor takes the class from the config of the model: RTDetrImageProcessor
        detector_input=cast(
            "transformers.RTDetrImageProcessor",
            transformers.AutoImageProcessor.from_pretrained(detector, revision=detector_revision),
        ),
        detector=transformers.RTDetrV2ForObjectDetection.from_pretrained(detector, revision=detector_revision)
        .to(device)  # type: ignore[arg-type]
        .eval(),
        reader_input=transformers.PaddleOCRVLProcessor.from_pretrained(reader, revision=reader_revision),
        reader=transformers.PaddleOCRVLForConditionalGeneration.from_pretrained(
            reader, revision=reader_revision, dtype=torch.bfloat16
        )
        .to(device)  # type: ignore[arg-type]
        .eval(),
    )

    return models


def unload() -> None:
    """Give the models' GPU memory back (when they are loaded)."""
    global models
    if not models:
        return
    models = None
    gc.collect()
    torch.cuda.empty_cache()


def read_chapter(chapter_id: int) -> str:
    """Read every page of the chapter and save the result. Returns the summary line."""
    started_at = time.time()
    models = load()
    chapter = suwayomi.chapter(chapter_id)

    # 1. For each page, find its text regions and where its panels start. A page that the source
    # cannot deliver is kept with its error.
    pages: list[TextPage] = []
    dropped = 0
    for index, img, error in page_images(chapter):
        if img is None:
            pages.append(TextPage(index=index, error=error, regions=[]))
            continue

        regions, without_words = read_page(img, models)
        dropped += without_words
        panels = ads.panel_tops(img)  # stops for the reader's click-scroll
        pages.append(
            TextPage(index=index, width=img.width, height=img.height, regions=regions, panels=panels)
        )

    # 2. Save the result, with the models that read it and the time.
    result = ChapterText(
        chapter_id=chapter.id,
        manga_id=chapter.manga_id,
        source_order=chapter.source_order,
        chapter=f"{chapter.manga.title} {chapter.name}",
        models={"detector": OCR_DETECTOR, "reader": OCR_READER},
        created=datetime.datetime.now().isoformat(sep=" ", timespec="seconds"),
        dropped=dropped,
        missing_pages=[p.index for p in pages if p.error is not None],
        pages=pages,
    )
    save(result)

    # 3. Write a line to the log.
    kept = sum(len(p.regions) for p in pages)
    summary = (
        f"chapter {chapter.id} ({result.chapter}): {kept} text regions on {len(pages)} pages, "
        f"{dropped} without words dropped, {len(result.missing_pages)} pages missing, "
        f"{time.time() - started_at:.0f}s"
    )
    log.info(summary)
    return summary


def read_page(img: Image.Image, m: Models) -> tuple[list[Region], int]:
    """The text regions of one page: found by the detector, read by the reader, cleaned up.
    Returns them, and how many were dropped for holding no word."""
    regions: list[Region] = []
    dropped = 0
    for box, kind in detect(img, m):
        text = clean(read(img.crop(box), m))
        if text is None:
            dropped += 1
            continue
        # The box as fractions of the width and height of the page. Then it fits the upscaled page too.
        fractions = [round(v / s, 5) for v, s in zip(box, (img.width, img.height) * 2, strict=True)]
        regions.append(Region(box=fractions, kind=kind, text=text))
    return regions, dropped


def save(result: ChapterText) -> None:
    """Write a chapter's text (what read_chapter makes) to OCR_DIR/<chapterId>.json."""
    os.makedirs(OCR_DIR, exist_ok=True)
    path = os.path.join(OCR_DIR, f"{result.chapter_id}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=1, exclude_none=True))  # a page in error has no size
    os.replace(path + ".tmp", path)  # atomic: the reader never gets a half-written file


def has_text(chapter_id: int) -> bool:
    return os.path.exists(os.path.join(OCR_DIR, f"{chapter_id}.json"))


def saved(chapter_id: int) -> ChapterText | None:
    """The saved text of a chapter (what read_chapter wrote), or None."""
    try:
        with open(os.path.join(OCR_DIR, f"{chapter_id}.json"), encoding="utf-8") as f:
            return ChapterText.model_validate_json(f.read())
    except FileNotFoundError:
        return None


def page_images(ch: Chapter) -> Iterator[tuple[int, Image.Image | None, str]]:
    """Yields (page index, RGB image, "") for each page, from the download folder or through the
    server. Yields (page index, None, error) for a page that the source cannot deliver (for
    example, the source answered 404)."""
    # A downloaded chapter: read its page files.
    if ch.is_downloaded:
        folder = suwayomi.download_folder(ch)
        for index, name in enumerate(suwayomi.page_files(folder)):
            # RGB, because the detector and the reader take 3 colour channels. A page from a source
            # can be grayscale, a palette PNG, or have a transparent layer. Pages that readahead
            # saved are RGB JPEGs already, and for them convert() only makes a copy.
            with Image.open(os.path.join(folder, name)) as img:
                yield index, img.convert("RGB"), ""
        return

    # Otherwise, get the pages through the server, which gets each page from the source.
    for index, url in enumerate(suwayomi.page_list(ch.id)):
        for attempt in (1, 2):  # a source sometimes fails a page: try once more after 5 s
            try:
                yield index, Image.open(io.BytesIO(suwayomi.fetch(url))).convert("RGB"), ""
                break
            except OSError as exc:  # also HTTP errors and broken images
                if attempt == 2:
                    log.warning("chapter %s page %s: %s", ch.id, index, exc)
                    yield index, None, str(exc)
                else:
                    time.sleep(5)


def detect(img: Image.Image, m: Models) -> list[tuple[Box, TextKind]]:
    """Text regions as ([x0, y0, x1, y1] in pixels, kind), from top to bottom.

    The detector resizes each image to 640x640. A webtoon strip is ten or more times taller than
    it is wide. If the whole strip was resized, its text would be a few pixels tall, and the
    detector would not find it. So the strip goes through in tiles:

    - A tile has the full width of the page. Its height is TILE (1.5) page widths. This shape is
      approximately the shape of the images that the detector was trained on.
    - Each tile starts TILE - OVERLAP (1.0) page widths below the start of the tile before it. So
      two tiles that follow each other have OVERLAP (0.5) page widths of rows in common.

    For a page 800 px wide and 2,800 px tall, each tile is 1,200 px tall:

        tile 1  rows     0 ... 1,200
        tile 2  rows   800 ... 2,000      rows 800 ... 1,200 are in tile 1 and in tile 2
        tile 3  rows 1,600 ... 2,800      the last tile always ends at the bottom of the page

    The edge of a tile can go through a bubble. Then the tile has only a part of the bubble. So
    detect_tile drops each region that touches the top or bottom edge of its tile, unless that
    edge is also the edge of the page. The tile next
    to it has the whole bubble, because the common rows (400 px here) are taller than almost
    every bubble. A region that is fully in the common rows is found by both tiles. Non-maximum
    suppression (NMS) then keeps the more confident of two boxes that mostly cover each other.
    """
    w, h = img.size

    # 1. Where the tiles start: every `step` rows. If the last tile ends above the bottom of the
    # page, add one more tile that ends at the bottom.
    tile_h, step = int(w * TILE), int(w * (TILE - OVERLAP))
    tops = list(range(0, max(1, h - tile_h) + 1, step))
    if tops[-1] + tile_h < h:
        tops.append(h - tile_h)

    # 2. Send each tile through the detector.
    found: list[tuple[Box, float, TextKind]] = []  # (box in page pixels, confidence, kind)
    for top in tops:
        found += detect_tile(img.crop((0, top, w, min(h, top + tile_h))), top, h, m)
    if not found:
        return []

    # 3. Keep one box when two tiles found the same region. Of two boxes that overlap by more
    # than half (intersection over union > 0.5), keep only the more confident one.
    boxes = torch.tensor([b for b, _, _ in found])
    scores = torch.tensor([s for _, s, _ in found])
    keep = torchvision.ops.nms(boxes, scores, 0.5)  # the indexes of the boxes to keep

    # 4. Add a small margin around each region, so the reader gets whole letters. Sort them from
    # top to bottom.
    pad = w * PAD
    regions: list[tuple[Box, TextKind]] = []
    for i in keep.tolist():
        (x0, y0, x1, y1), _, kind = found[i]
        regions.append(((max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)), kind))
    return sorted(regions, key=lambda r: (r[0][1], r[0][0]))


def detect_tile(
    tile: Image.Image, top: int, page_height: int, m: Models
) -> list[tuple[Box, float, TextKind]]:
    """The text regions that the detector finds on one tile, as (box in page pixels, confidence,
    kind). The tile starts `top` rows down the page. A region that the top or bottom edge of the
    tile cuts is left out, unless that edge is also the edge of the page. The next tile has that
    region whole."""
    inputs = m.detector_input(images=tile, return_tensors="pt").to(device)
    with torch.inference_mode():
        out = m.detector(**inputs)
    res = m.detector_input.post_process_object_detection(
        out, threshold=THRESHOLD, target_sizes=[(tile.height, tile.width)]
    )[0]
    found: list[tuple[Box, float, TextKind]] = []
    for box, score, label in zip(
        res["boxes"].tolist(), res["scores"].tolist(), res["labels"].tolist(), strict=True
    ):
        x0, y0, x1, y1 = box  # in tile pixels
        cut = (y0 < 2 and top > 0) or (y1 > tile.height - 2 and top + tile.height < page_height)
        if label in KINDS and not cut:
            found.append(((x0, y0 + top, x1, y1 + top), score, KINDS[label]))
    return found


def read(crop: Image.Image, m: Models) -> str:
    """The text in one region, as PaddleOCR-VL reads it.

    PaddleOCR-VL is a small vision-language model. It gets a request like a chat model: one
    message with the image and the task ("OCR:" means "read the text"). It answers in tokens.
    With do_sample=False it always picks the most likely token, so the same crop always gives
    the same text.
    """
    processor = m.reader_input  # turns image + prompt into the model's input tensors
    content = [{"type": "image", "image": crop}, {"type": "text", "text": "OCR:"}]
    message = {"role": "user", "content": content}
    # transformers declares the messages as text only, the result as a string, and generate()
    # for a different kind of model. With these arguments, the result is the input tensors of
    # the model (a BatchFeature), and generate() returns the tokens. The casts and "type: ignore"
    # tell the type checker this.
    inputs = cast(
        "transformers.BatchFeature",
        processor.apply_chat_template(
            [message],  # type: ignore[arg-type]
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ),
    ).to(device)
    with torch.inference_mode():
        out = cast(
            torch.Tensor,
            m.reader.generate(**inputs, max_new_tokens=256, do_sample=False),  # type: ignore[misc]
        )
    # generate() returns the prompt and the answer. Keep the answer.
    new = out[:, inputs["input_ids"].shape[1] :]
    answer: str = processor.batch_decode(new, skip_special_tokens=True)[0]
    return answer


def clean(text: str) -> str | None:
    """The text in lowercase, with look-alike letters changed to Latin and spaces made regular.
    None when the text holds no word (two Latin letters in a row), or when it is mostly in
    another script (Korean sound effects). Comics use capital letters, and a dictionary or
    translator wants lowercase."""
    text = " ".join(text.translate(LOOKALIKES).split())
    letters = [c for c in text if c.isalpha()]
    if not re.search(r"[A-Za-z]{2}", text) or sum(c.isascii() for c in letters) < 0.8 * len(letters):
        return None
    return text.lower()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: ocr.py <chapterId>")
    read_chapter(int(sys.argv[1]))
