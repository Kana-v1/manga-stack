"""The page files of a downloaded chapter: cut the ads out of them (ads.py), and upscale them on
the GPU.

Each page changes in place: the same folder, the same page number, saved as JPEG. A page that is
SKIP_WIDTH wide or wider is not upscaled. An upscaled page gets a JPEG comment (UPSCALED), so no
page is upscaled twice.
"""

import os
from typing import cast

import numpy as np
import numpy.typing as npt
import torch
from PIL import Image
from spandrel import ImageModelDescriptor, ModelLoader

import ads
from config import JPEG_QUALITY, MODEL_PATH, SKIP_WIDTH
from datatypes import Chapter, PageHeader, TextPage
from suwayomi import download_folder, page_files

BAND_PIXELS = 1_500_000  # input pixels per GPU pass: a 25,000 px strip does not fit in one pass
OVERLAP = 24  # extra rows above and below each band, removed after upscaling
Image.MAX_IMAGE_PIXELS = 400_000_000  # webtoon strips are tall, and the files are our own downloads

type Pixels = npt.NDArray[np.uint8]  # an image as rows x columns x 3 colour bytes (red, green, blue)

loaded = ModelLoader().load_from_file(MODEL_PATH)
if not isinstance(loaded, ImageModelDescriptor):  # not an inpainting model, which needs a mask
    raise SystemExit(f"{MODEL_PATH} is not an image-to-image model")
model: ImageModelDescriptor[torch.nn.Module] = loaded
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
dtype = torch.float16 if device.type == "cuda" and model.supports_half else torch.float32
model.to(device).eval()
if dtype == torch.float16:
    model.half()


# ---------------------------------------------------------------- which pages are upscaled

# A JPEG comment in each page file that readahead upscaled. Only this comment shows that a page
# is upscaled. The server does not know about upscaling, and a wide page can be an original.
UPSCALED = b"manga-stack: upscaled"


def is_done(ch: Chapter) -> bool:
    """True when the chapter is downloaded and no page needs an upscale (needs_upscale). A pass
    queues the chapters that are not done."""
    return ch.is_downloaded and not any(needs_upscale(h) for h in page_headers(ch))


def is_upscaled(ch: Chapter) -> bool:
    """True when the chapter is done and readahead upscaled at least one of its pages. Only these
    chapters get the "HD" mark (tags.py). A chapter whose original pages are all SKIP_WIDTH wide
    or wider is done, but it is not upscaled."""
    if not ch.is_downloaded:
        return False
    headers = page_headers(ch)
    return not any(needs_upscale(h) for h in headers) and any(h.upscaled for h in headers)


def needs_upscale(h: PageHeader) -> bool:
    """True when the page is narrower than SKIP_WIDTH and readahead did not upscale it yet. An
    original page that is narrower than SKIP_WIDTH / 2 stays narrower after the upscale. The
    comment stops a second upscale of it."""
    return h.width < SKIP_WIDTH and not h.upscaled


def page_headers(ch: Chapter) -> list[PageHeader]:
    """The header of each page file of a downloaded chapter."""
    folder = download_folder(ch)
    headers: list[PageHeader] = []
    for name in page_files(folder):
        with Image.open(os.path.join(folder, name)) as img:  # reads the header only, not the pixels
            headers.append(header(img))
    return headers


def header(img: Image.Image) -> PageHeader:
    return PageHeader(width=img.width, upscaled=img.info.get("comment") == UPSCALED)


# ---------------------------------------------------------------- one page


def process(path: str, text: TextPage | None, title: str) -> tuple[list[tuple[float, float]], bool]:
    """Cut the ads out of one page file, then upscale it if it is not wide enough. The result is
    saved once. `text` is the recognised text of the page (ocr.py), which finds the ads. It is
    None when the page has no text. Returns the rows cut (as fractions of the page height) and
    whether the page was upscaled."""
    # 1. Find out if there is work to do. Image.open() reads only the header of the file, not the
    # pixels.
    with Image.open(path) as img:
        before = header(img)
        # the text of the page, unless it was read from a different version of the page
        regions = text.regions if text and ads.same_page(text, img.size) else []
        has_ads = any(ads.AD_TEXT.search(r.text) for r in regions)
        if not needs_upscale(before) and not has_ads:
            return [], False
        page = img.convert("RGB")

    # 2. Cut the ads out (ads.py). Return the cuts as fractions of the page height. The text boxes
    # use this unit, and ads.shift() moves them with the cuts.
    rows = ads.find_cuts(page, regions, title)[0] if has_ads else []
    # Rows in pixels -> fractions of the page height (row 500 of 1000 is 0.5). A fraction stays
    # right after the 2x upscale, which doubles the rows.
    cuts = [(top / page.height, bottom / page.height) for top, bottom in rows]
    if rows:
        page = ads.cut(page, rows)

    # 3. Upscale the page if it is not wide enough and not upscaled yet. The GPU gets one page at
    # a time, because jobs.py runs one job at a time.
    upscale = needs_upscale(before)
    if upscale:
        page = Image.fromarray(upscale_rgb(np.array(page)))

    # 4. Save the page once, for any change. A page that is upscaled now or before keeps the
    # UPSCALED comment.
    if cuts or upscale:
        save(path, page, upscaled=upscale or before.upscaled)
    return cuts, upscale


def save(path: str, page: Image.Image, upscaled: bool) -> None:
    """Replace the page file. The format is JPEG, not WebP: WebP limits a side to 16,383 px, and
    a 2x strip is taller. The server finds a page by its number ("001"), so a .png can become a
    .jpg. An upscaled page gets the UPSCALED comment."""
    target = os.path.splitext(path)[0] + ".jpg"
    page.save(target + ".tmp", "JPEG", quality=JPEG_QUALITY, comment=UPSCALED if upscaled else b"")
    os.replace(target + ".tmp", target)  # atomic: the server never reads a half-written page
    if target != path:
        os.remove(path)


def upscale_rgb(rgb: Pixels) -> Pixels:
    """Upscale an HxWx3 uint8 array by the scale of the model.

    A full webtoon strip does not fit in GPU memory. So it goes through in bands of the full
    width and about BAND_PIXELS pixels. The model uses the pixels near each pixel, so a band
    with a sharp edge would show a seam where it meets the next band. To prevent this, each band
    goes through with OVERLAP extra rows above and below. Only the rows of the band itself are
    kept from the result:

        rows y .. y+band of the input  ->  rows (y-top)*scale .. +band*scale of the band's output
    """
    height, width, _ = rgb.shape
    band = max(64, BAND_PIXELS // width)  # rows per band
    scale: int = model.scale  # 2 for a 2x model
    parts: list[Pixels] = []
    for y in range(0, height, band):
        top, bottom = max(0, y - OVERLAP), min(height, y + band + OVERLAP)  # the band and its overlap
        out = run_model(rgb[top:bottom])
        start = (y - top) * scale  # skip the upscaled overlap above the band
        rows = (min(height, y + band) - y) * scale  # the band's own rows (the last band may be short)
        parts.append(out[start : start + rows])
    return np.concatenate(parts)


def run_model(rgb: Pixels) -> Pixels:
    """One pass of the model over an HxWx3 uint8 array."""
    # 1. The pixels to the GPU, in the layout and unit that the model takes.
    t = torch.from_numpy(np.ascontiguousarray(rgb)).to(device)  # a tensor in GPU memory
    t = t.permute(2, 0, 1)  # H x W x 3 (a pixel's 3 colours together) -> 3 x H x W (3 colour planes)
    t = t.unsqueeze(0)  # -> 1 x 3 x H x W: a batch of 1 image
    t = t.to(dtype).div_(255)  # bytes 0..255 -> numbers 0..1 (fp16)

    # Steps 2 and 3 are in inference_mode: no record for training, which saves memory and time.
    # PyTorch lets a tensor made in this mode change in place (clamp_, mul_) only in this mode.
    with torch.inference_mode():
        # 2. The model.
        out = model(t)  # 1 x 3 x 2H x 2W, numbers about 0..1
        # 3. Back to bytes. The model can give a little below 0 or above 1: clamp_ cuts that
        #    off. Then 0..1 -> 0..255, rounded to whole numbers. (A name with _ changes the
        #    tensor in place.)
        out = out.clamp_(0, 1).mul_(255).round_().to(torch.uint8)

    # 4. Back to the layout of step 1, reversed, in normal memory: 2H x 2W x 3.
    out = out.squeeze(0)  # remove the batch of 1: 3 x 2H x 2W
    out = out.permute(1, 2, 0)  # 3 colour planes -> a pixel's 3 colours together
    return cast(Pixels, out.cpu().numpy())  # from GPU memory to a numpy array
