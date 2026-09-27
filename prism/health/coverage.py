"""Read line coverage per file from an existing coverage report, if there is one.

Supports Cobertura XML (`coverage.xml`, as written by `coverage xml` / pytest-cov)
and coverage.py JSON (`coverage.json`). PRISM never runs coverage itself.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

CANDIDATES = ("coverage.xml", "coverage.json", "cov.xml", "build/coverage.xml")


def _match(path: str, indexed: set[str]) -> str | None:
    path = path.replace("\\", "/").lstrip("./")
    if path in indexed:
        return path
    hits = [f for f in indexed if f.endswith("/" + path) or path.endswith("/" + f)]
    return hits[0] if len(hits) == 1 else None


def read_coverage(root: Path, indexed: set[str]) -> dict[str, float]:
    for name in CANDIDATES:
        path = root / name
        if not path.is_file():
            continue
        try:
            if name.endswith(".json"):
                return _from_json(path, indexed)
            return _from_xml(path, indexed)
        except (OSError, ValueError, ET.ParseError, KeyError, TypeError):
            continue
    return {}


def _from_xml(path: Path, indexed: set[str]) -> dict[str, float]:
    # Coverage reports are produced locally by the user's own tooling.
    tree = ET.parse(path)
    out: dict[str, float] = {}
    for cls in tree.iter("class"):
        match = _match(cls.get("filename", ""), indexed)
        if match is not None:
            out[match] = round(float(cls.get("line-rate", "0")), 3)
    return dict(sorted(out.items()))


def _from_json(path: Path, indexed: set[str]) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for fname, info in data.get("files", {}).items():
        match = _match(fname, indexed)
        if match is not None:
            out[match] = round(float(info["summary"]["percent_covered"]) / 100.0, 3)
    return dict(sorted(out.items()))
