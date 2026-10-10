"""Agent activity trail: `.aicontext/cache/activity.log` (JSON lines, capped, gitignored).

Records only operation names and symbol/file ids, never code. The viewer
streams it to highlight what the agent is looking at.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from pathlib import Path

MAX_LINES = 1000
KEEP_LINES = 500


# The viewer answers its own clicks with the same navigator functions the agent uses; those
# lookups are the person browsing, not the agent working, and must not light up the trail.
_QUIET: ContextVar[bool] = ContextVar("prism_activity_quiet", default=False)


@contextlib.contextmanager
def quiet_activity() -> Iterator[None]:
    """Navigator calls inside this block are not recorded as agent activity."""
    token = _QUIET.set(True)
    try:
        yield
    finally:
        _QUIET.reset(token)


def activity_path(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / "activity.log"


def record_activity(root: Path, op: str, ids: Iterable[str]) -> None:
    if _QUIET.get():
        return
    path = activity_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"t": round(time.time(), 3), "op": op, "ids": sorted(set(ids))[:50]}
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        if path.stat().st_size > MAX_LINES * 200:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_LINES:
                path.write_text(
                    "\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8", newline="\n"
                )
    except OSError:
        pass  # the trail is best-effort and must never break a query


def read_activity(root: Path, since: float = 0.0) -> list[dict[str, object]]:
    path = activity_path(root)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and float(event.get("t", 0)) > since:
            out.append(event)
    return out
