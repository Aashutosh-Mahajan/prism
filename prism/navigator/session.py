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

from prism.writers.manifest import load_manifest

SESSION_TTL_SECONDS = 6 * 3600
MAX_RANGES = 300

Range = tuple[str, int, int]


def _path(root: Path, session: str) -> Path:
    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
    from prism.consent import cache_root

    return cache_root(root) / "sessions" / f"{digest}.json"


def clear_seen(root: Path, session: str) -> None:
    """A cleared/compacted host context no longer contains delivered source."""
    _path(root, session).unlink(missing_ok=True)


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


def query_key(query: str) -> str:
    """Stable key of a request, used to tell an identical retry from a new request."""
    return hashlib.sha256(" ".join(query.split()).lower().encode("utf-8")).hexdigest()[:16]


def _read(
    path: Path, manifest: dict[str, Any] | None, root: Path
) -> tuple[set[Range], dict[str, Any] | None]:
    """(committed ranges of unchanged source, pending delivery record) from a session file."""
    try:
        if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
            return set(), None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in (2, 3):
            return set(), None  # older caches did not distinguish delivered from truncated code
        current = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
        previous = data["hashes"]
        if not isinstance(previous, dict):
            return set(), None
        committed = {
            (str(f), int(a), int(b))
            for f, a, b in data["ranges"]
            if f in current and previous.get(f) == current[f] and 0 < int(a) <= int(b)
        }
        pending = data.get("pending") if data.get("version") == 3 else None
        return committed, pending if isinstance(pending, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return set(), None


def load_seen(
    root: Path, session: str, manifest: dict[str, Any] | None = None, query: str | None = None
) -> set[Range]:
    """Ranges the client is known to have received, from unchanged source only.

    A reply is only *proven* delivered when the same session makes a different next request: the
    client cannot ask again without having read the answer. So the ranges a previous call left
    pending are committed by a different `query`; an identical `query` is a retry (the reply was
    lost, cancelled or never read), which drops the pending ranges so the source is sent again.
    Without a `query` pending ranges stay pending (they are never treated as delivered)."""
    path = _path(root, session)
    committed, pending = _read(path, manifest, root)
    if pending and query is not None:
        if pending.get("query") != query_key(query):
            hashes = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
            for f, a, b in pending.get("ranges", []):
                if (
                    f in hashes
                    and pending.get("hashes", {}).get(f) == hashes[f]
                    and 0 < int(a) <= int(b)
                ):
                    committed.add((str(f), int(a), int(b)))
            _write(path, root, committed, None, manifest)
        else:
            _write(
                path, root, committed, None, manifest
            )  # identical retry: resend, forget the lost reply
    return committed


def _write(
    path: Path,
    root: Path,
    ranges_in: set[Range],
    pending: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        hashes = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
        merged: list[Range] = []
        for file, start, end in sorted(ranges_in):
            if file not in hashes or not 0 < start <= end:
                continue
            if merged and merged[-1][0] == file and start <= merged[-1][2] + 1:
                previous = merged[-1]
                merged[-1] = (file, previous[1], max(previous[2], end))
            else:
                merged.append((file, start, end))
        ranges = merged[-MAX_RANGES:]
        record: dict[str, Any] = {
            "version": 3,
            "hashes": {file: hashes[file] for file in sorted({r[0] for r in ranges})},
            "ranges": [list(r) for r in ranges],
        }
        if pending and pending.get("ranges"):
            record["pending"] = pending
        tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
        _prune(path.parent, time.time())
    except (OSError, ValueError, TypeError):
        pass  # dedupe is an optimisation; never fail a query over it


def save_seen(
    root: Path,
    session: str,
    seen: set[Range],
    manifest: dict[str, Any] | None = None,
    query: str | None = None,
    committed: set[Range] | None = None,
) -> None:
    """Remember what a call returned. With `query` (and the `committed` set it started from) the
    new ranges are only recorded as pending until a later, different request proves delivery;
    without it they are committed immediately (used where output is injected, e.g. hooks)."""
    path = _path(root, session)
    if query is None:
        _write(path, root, seen, None, manifest)
        return
    base = committed if committed is not None else set()
    delta = sorted(seen - base)
    hashes = _hashes(manifest if manifest is not None else (load_manifest(root) or {}))
    pending = {
        "query": query_key(query),
        "ranges": [list(r) for r in delta if r[0] in hashes],
        "hashes": {r[0]: hashes[r[0]] for r in delta if r[0] in hashes},
    }
    _write(path, root, set(base), pending, manifest)


ACTIVE_TTL_SECONDS = 30 * 60


def _active_path(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / "sessions" / "active"


def note_active_session(root: Path, session: str | None) -> None:
    """Advertise a host session without overwriting another live conversation.

    Separate markers avoid last-writer-wins races between hooks in the same repo.
    An implicit tool session is safe only when exactly one recent host is known.
    """
    if not session:
        return
    directory = _active_path(root)
    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
    path = directory / f"{digest}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(session, encoding="utf-8")
    except OSError:
        pass


def active_session(root: Path) -> str | None:
    """Infer a session only when unambiguous; otherwise resend rather than hide source."""
    try:
        active: set[str] = set()
        now = time.time()
        for path in _active_path(root).glob("*.txt"):
            if now - path.stat().st_mtime > ACTIVE_TTL_SECONDS:
                path.unlink(missing_ok=True)
                continue
            value = path.read_text(encoding="utf-8").strip()
            if value:
                active.add(value)
            if len(active) > 1:
                return None
        return next(iter(active), None)
    except OSError:
        return None


def session_id(explicit: str | None, root: Path | None = None) -> str | None:
    """The session to remember ranges in: an explicit id, `PRISM_SESSION`, else the hook's session.

    The CLI and MCP tools cannot see the host agent's session id, but the prompt hook can: it
    advertises its session. Reuse it only when no other recent host session makes
    that inference ambiguous. Explicit IDs always take precedence.
    """
    chosen = explicit or os.environ.get("PRISM_SESSION")
    if chosen:
        return chosen
    return active_session(root) if root is not None else None
