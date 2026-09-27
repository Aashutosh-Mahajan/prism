"""Marked regions in agent-facing Markdown.

<!-- prism:generated:facts -->
...owned by PRISM...
<!-- /prism:generated:facts -->

<!-- prism:narrative:purpose -->
...owned by the host agent...
<!-- /prism:narrative:purpose -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RegionKind = Literal["generated", "narrative"]

_REGION = re.compile(
    r"<!-- prism:(generated|narrative):([a-z0-9_-]+) -->\n(.*?)<!-- /prism:\1:\2 -->",
    re.DOTALL,
)


@dataclass(frozen=True)
class Region:
    kind: RegionKind
    name: str
    body: str


def open_marker(kind: RegionKind, name: str) -> str:
    return f"<!-- prism:{kind}:{name} -->"


def close_marker(kind: RegionKind, name: str) -> str:
    return f"<!-- /prism:{kind}:{name} -->"


def render_region(kind: RegionKind, name: str, body: str) -> str:
    body = body.strip("\n")
    inner = f"{body}\n" if body else ""
    return f"{open_marker(kind, name)}\n{inner}{close_marker(kind, name)}"


def parse_regions(text: str) -> dict[tuple[RegionKind, str], Region]:
    text = text.replace("\r\n", "\n")
    out: dict[tuple[RegionKind, str], Region] = {}
    for m in _REGION.finditer(text):
        kind: RegionKind = "generated" if m.group(1) == "generated" else "narrative"
        out[(kind, m.group(2))] = Region(kind, m.group(2), m.group(3).strip("\n"))
    return out
