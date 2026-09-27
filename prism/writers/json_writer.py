"""Byte-stable file writing: sorted keys, LF endings, atomic replace, skip if unchanged."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def write_json(path: Path, data: Any) -> bool:
    return write_text(path, dumps(data))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
