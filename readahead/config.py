"""Settings, from the stack.conf file of the project. An environment variable with the same name
has priority. scripts/lib.ts reads the file in the same way. Put a new setting in stack.conf and
here, and nowhere else. The settings are read once at startup, so a change needs a restart."""

import os
import re

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_conf() -> dict[str, str]:
    """Read KEY="value" lines in shell syntax. A quoted value can continue on the next lines.
    Outside quotes, # starts a comment. ~, $VAR, ${VAR} and ${VAR:-default} get their values
    from the environment."""
    with open(os.path.join(PROJECT, "stack.conf"), encoding="utf-8") as f:
        text = f.read()
    values: dict[str, str] = {}
    # KEY="value" (can continue on the next lines), KEY='value', or KEY=value up to a # or the end of the line
    for m in re.finditer(r'^\s*([A-Z_][A-Z0-9_]*)=(?:"([^"]*)"|\'([^\']*)\'|([^#\n]*))', text, re.MULTILINE):
        key, *forms = m.groups()  # forms: the double-quoted, single-quoted and bare value. One is set.
        value = next(v for v in forms if v is not None).strip()
        values[key] = expand(os.environ.get(key, value))
    return values


def expand(value: str) -> str:
    def variable(m: re.Match[str]) -> str:
        name, default = m.group(1) or m.group(3), m.group(2)
        return os.environ.get(name) or (expand(default) if default is not None else "")

    value = re.sub(r"\$\{(\w+)(?::-([^}]*))?\}|\$(\w+)", variable, value)
    return os.path.expanduser(value)


CONFIG = read_conf()

PORT = int(CONFIG["READAHEAD_PORT"])
MODEL_PATH = os.path.join(PROJECT, CONFIG["UPSCALE_MODEL"])  # an absolute path stays as it is

# Pages this wide or wider are not changed: they are upscaled already, or sharp enough.
SKIP_WIDTH = int(CONFIG["UPSCALE_SKIP_WIDTH"])
JPEG_QUALITY = int(CONFIG["UPSCALE_JPEG_QUALITY"])

# How many unread chapters per title to keep upscaled ahead of the reader.
AHEAD = int(CONFIG["UPSCALE_AHEAD"])
# Minutes between passes. 0 stops the scheduled passes.
INTERVAL_MINUTES = int(CONFIG["READAHEAD_INTERVAL_MINUTES"])

# Text recognition (ocr.py): Hugging Face models as "repository@revision". stack.conf gives a
# commit as the revision, so a new version of a model does not change the results by surprise.
# OCR_DETECTOR: an RT-DETR-v2 detector with the classes that ocr.py expects (ocr.KINDS): 0 the
#   outline of a bubble, 1 text in a bubble, 2 text outside bubbles.
#   "ogkalu/comic-text-and-bubble-detector@<commit>".
# OCR_READER: a PaddleOCR-VL model, which reads the text in one region. "PaddlePaddle/PaddleOCR-VL@<commit>".
OCR_DETECTOR = CONFIG["OCR_DETECTOR"]
OCR_READER = CONFIG["OCR_READER"]
# How many unread chapters per title get their text read ahead of the reader. 0 stops this.
OCR_AHEAD = int(CONFIG["OCR_AHEAD"])

SERVER_URL = CONFIG["SUWAYOMI_URL"].rstrip("/")
DATA_DIR = CONFIG["TACHIDESK_DATA"]

# State, in the same folder as the logs (STATE_DIR in scripts/lib.ts).
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
STATE_DIR = os.path.join(STATE_HOME, "manga-stack")
# The chapters whose download readahead made (download_record.py). It deletes only these downloads.
DOWNLOAD_RECORD_FILE = os.path.join(STATE_DIR, "readahead-downloads.json")
# One line per pass (history.py).
HISTORY_FILE = os.path.join(STATE_DIR, "readahead-passes.jsonl")
# The text of the chapters, one JSON file for each chapter (ocr.py).
OCR_DIR = os.path.join(STATE_DIR, "ocr")
