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
from pathlib import Path

from prism.core.paths import AICONTEXT

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


def load_seen(root: Path, session: str) -> set[Range]:
    """Ranges returned earlier in `session` (empty if the session is new or has expired)."""
    path = _path(root, session)
    try:
        if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
            return set()
        data = json.loads(path.read_text(encoding="utf-8"))
        return {(str(f), int(a), int(b)) for f, a, b in data["ranges"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def save_seen(root: Path, session: str, seen: set[Range]) -> None:
    path = _path(root, session)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ranges = sorted(seen)[-MAX_RANGES:]
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"ranges": [list(r) for r in ranges]}), encoding="utf-8")
        os.replace(tmp, path)
        _prune(path.parent, time.time())
    except OSError:
        pass  # dedupe is an optimisation; never fail a query over it


def session_id(explicit: str | None) -> str | None:
    """The session to remember ranges in: an explicit id, else `PRISM_SESSION`."""
    return explicit or os.environ.get("PRISM_SESSION") or None
