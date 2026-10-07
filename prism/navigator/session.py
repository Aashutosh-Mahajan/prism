"""Per-session memory of the code ranges already returned, so a repeat costs a reference line.

The MCP server keeps this in memory for its lifetime. A CLI caller opts in with
`--session <id>` (or `PRISM_SESSION`); the ranges are then kept in a small file under
`.aicontext/cache/sessions/`, which is gitignored and pruned after a few hours.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from prism.core.paths import AICONTEXT
from prism.writers.manifest import load_manifest

SESSION_TTL_SECONDS = 6 * 3600
MAX_RANGES = 300

Range = tuple[str, int, int]


def _path(root: Path, session: str) -> Path:
    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
    return root / AICONTEXT / "cache" / "sessions" / f"{digest}.json"


def _prune(directory: Path, now: float) -> None:
    try:
        for entry in directory.glob("*.json"):
            if now - entry.stat().st_mtime > SESSION_TTL_SECONDS:
                entry.unlink(missing_ok=True)
    except OSError:
        pass


def _hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        file: facts["sha256"]
        for file, facts in manifest.get("files", {}).items()
        if isinstance(facts, dict) and isinstance(facts.get("sha256"), str)
    }


def load_seen(root: Path, session: str, manifest: dict[str, Any] | None = None) -> set[Range]:
    """Delivered ranges from unchanged source only; legacy caches are re-read once."""
    path = _path(root, session)
    try:
        if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
            return set()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            return set()  # older caches did not distinguish delivered from truncated code
        current = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
        previous = data["hashes"]
        if not isinstance(previous, dict):
            return set()
        return {
            (str(f), int(a), int(b))
            for f, a, b in data["ranges"]
            if f in current and previous.get(f) == current[f] and 0 < int(a) <= int(b)
        }
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def save_seen(
    root: Path, session: str, seen: set[Range], manifest: dict[str, Any] | None = None
) -> None:
    path = _path(root, session)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        hashes = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
        merged: list[Range] = []
        for file, start, end in sorted(seen):
            if file not in hashes or not 0 < start <= end:
                continue
            if merged and merged[-1][0] == file and start <= merged[-1][2] + 1:
                previous = merged[-1]
                merged[-1] = (file, previous[1], max(previous[2], end))
            else:
                merged.append((file, start, end))
        ranges = merged[-MAX_RANGES:]
        tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": 2,
                    "hashes": {file: hashes[file] for file in sorted({r[0] for r in ranges})},
                    "ranges": [list(r) for r in ranges],
                }
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        _prune(path.parent, time.time())
    except (OSError, ValueError, TypeError):
        pass  # dedupe is an optimisation; never fail a query over it


def session_id(explicit: str | None) -> str | None:
    """The session to remember ranges in: an explicit id, else `PRISM_SESSION`."""
    return explicit or os.environ.get("PRISM_SESSION") or None
