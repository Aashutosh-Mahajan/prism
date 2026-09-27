"""Write agent-authored narrative into marked regions (used by `refresh commit`)."""

from __future__ import annotations

import re
from pathlib import Path

from prism.core.markers import close_marker, open_marker
from prism.writers.json_writer import write_text


def replace_narrative(text: str, name: str, body: str) -> str:
    start, end = open_marker("narrative", name), close_marker("narrative", name)
    pattern = re.compile(re.escape(start) + r"\n.*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise KeyError(name)
    replacement = f"{start}\n{body.strip()}\n{end}"
    return pattern.sub(lambda _m: replacement, text, count=1)


def write_narrative(path: Path, name: str, body: str) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    new = replace_narrative(text, name, body)
    write_text(path, new)
    return new
