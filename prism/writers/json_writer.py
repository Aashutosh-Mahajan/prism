"""Byte-stable file writing: sorted keys, LF endings, atomic replace, skip if unchanged."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPLACE_ATTEMPTS = 12
REPLACE_PAUSE_SECONDS = 0.01


def _replace(tmp: str, path: Path) -> None:
    """`os.replace`, retried briefly. On Windows the target cannot be replaced while another
    thread or process (a reader, an antivirus scan, the search indexer) has it open; that is
    over in milliseconds, so wait it out instead of failing the whole update."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE_SECONDS * (attempt + 1))


def dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_text(path: Path, text: str) -> bool:
    """Write `text` with LF newlines. Returns False if the file already had this content."""
    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def write_json(path: Path, data: Any) -> bool:
    return write_text(path, dumps(data))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
