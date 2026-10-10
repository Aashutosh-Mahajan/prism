"""Summaries of earlier sessions from the work log (`prism.writers.worklog`).

* `last_session_brief`: a few lines for the session-start hook: what the most recent other
  session asked, which files and functions it edited, and any handoff note.
* `recall`: recent sessions for `prism recall` / `prism_recall`, optionally ranked by a query.
* `related_history`: one or two lines for a task answer when an earlier session changed the
  same code, so its intent is not rediscovered from scratch.

Edits are logged as a file plus the first line of the new text; they are resolved to the
enclosing symbol here, against the current source, so a log never goes stale on renames.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from prism.core.tokens import estimate_tokens
from prism.writers.worklog import RECENT_DAYS, SessionLog, sessions

BRIEF_BUDGET = 140  # tokens for the session-start summary
MAX_FILES = 5
MAX_SYMBOLS_PER_FILE = 2
HISTORY_LINES = 2

_WORD = re.compile(r"\w{3,}")


def ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{round(minutes)} min ago"
    hours = minutes / 60
    if hours < 36:
        return f"{round(hours)} h ago"
    return f"{round(hours / 24)} days ago"


def _symbols_for(root: Path, file: str, anchors: list[str], store: Any) -> list[str]:
    """Names of the symbols the anchored edits landed in (current source)."""
    if store is None or not anchors:
        return []
    try:
        lines = (root / file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    names: list[str] = []
    for anchor in anchors:
        needle = anchor.strip().rstrip("…").strip()
        if len(needle) < 4:
            continue
        for number, text in enumerate(lines, 1):
            if needle in text:
                sym = store.symbol_at(file, number)
                if sym is not None:
                    short = sym.id.removeprefix(sym.module + ".") if sym.module else sym.name
                    if short not in names:
                        names.append(short)
                break
        if len(names) >= MAX_SYMBOLS_PER_FILE:
            break
    return names


def _open_store(root: Path) -> Any:
    """The query store if its caches are already built; a summary never builds them."""
    try:
        from prism.navigator.freshness import caches_ready
        from prism.navigator.store import IndexStore

        return IndexStore.open(root) if caches_ready(root) else None
    except Exception:
        return None


def describe(root: Path, log: SessionLog, store: Any, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    edited = []
    for file in list(log.edits)[:MAX_FILES]:
        edited.append({"file": file, "symbols": _symbols_for(root, file, log.edits[file], store)})
    return {
        "session": log.digest,
        "when": ago(now - log.updated),
        "updated": round(log.updated),
        "requests": log.requests[-3:],
        "edited": edited,
        "more_files": max(0, len(log.edits) - MAX_FILES),
        "looked_at": [s for s in log.focus if s][:4],
        "notes": log.notes[-3:],
    }


def render_session(info: dict[str, Any], heading: str = "Last session") -> str:
    lines = [f"{heading} ({info['when']}):"]
    requests = info["requests"]
    if requests:
        first = requests[0]
        extra = f" (+{len(requests) - 1} more)" if len(requests) > 1 else ""
        lines.append(f'  Asked: "{first}"{extra}')
    if info["edited"]:
        parts = [
            f"{e['file']} ({', '.join(e['symbols'])})" if e["symbols"] else e["file"]
            for e in info["edited"]
        ]
        more = f" +{info['more_files']} more" if info["more_files"] else ""
        lines.append("  Edited: " + ", ".join(parts) + more)
    elif info["looked_at"]:
        lines.append("  Looked at: " + ", ".join(info["looked_at"]))
    for note in info["notes"][-2:]:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


def _fit(text: str, budget: int) -> str:
    """Drop trailing lines (keeping the heading) until the text fits."""
    lines = text.splitlines()
    while len(lines) > 1 and estimate_tokens("\n".join(lines)) > budget:
        lines.pop()
    return "\n".join(lines)


def last_session_brief(root: Path, current: str | None = None, budget: int = BRIEF_BUDGET) -> str:
    """The most recent other session worth resuming from, in a few lines (or "")."""
    try:
        recent = sessions(root, exclude=current, days=RECENT_DAYS)
        # A session that changed code or left a note beats a later one that only looked around
        # (e.g. an MCP server's log of the same conversation the hooks recorded).
        candidates = [s for s in recent if s.edits or s.notes] or [s for s in recent if s.focus]
        if not candidates:
            return ""
        store = _open_store(root)
        try:
            info = describe(root, candidates[0], store)
        finally:
            if store is not None:
                store.close()
        text = (
            render_session(info)
            + "\n  (Verify against the code before relying on it; `prism recall` for more.)"
        )
        return _fit(text, budget)
    except Exception:
        return ""


def recall(
    root: Path, query: str | None = None, limit: int = 5, exclude: str | None = None
) -> dict[str, Any]:
    """Recent sessions (most recent first), or those that best match `query`."""
    logs = [s for s in sessions(root, exclude=exclude) if s.substantive or s.requests]
    if query:
        wanted = {w.lower() for w in _WORD.findall(query)}
        scored = [(len(wanted & s.words()), s) for s in logs]
        logs = [s for score, s in sorted(scored, key=lambda p: (-p[0], -p[1].updated)) if score]
    store = _open_store(root)
    try:
        items = [describe(root, s, store) for s in logs[:limit]]
    finally:
        if store is not None:
            store.close()
    return {"sessions": items, "query": query}


def render_recall(data: dict[str, Any]) -> str:
    if not data["sessions"]:
        return "No earlier sessions recorded" + (" for that query." if data.get("query") else ".")
    return "\n".join(render_session(s, heading="Session") for s in data["sessions"])


def related_history(
    root: Path, files: set[str], symbols: set[str], exclude: str | None = None
) -> list[str]:
    """One line per earlier session that edited these files or looked at these symbols."""
    if not files and not symbols:
        return []
    out: list[str] = []
    now = time.time()
    try:
        logs = sessions(root, exclude=exclude)
    except Exception:
        return []
    for log in logs:
        touched = sorted(files & set(log.edits))
        seen = sorted(symbols & set(log.focus))
        if not touched and not (seen and log.notes):
            continue
        what = f"edited {', '.join(touched[:2])}" if touched else f"worked on {seen[0]}"
        line = f"{ago(now - log.updated)}: {what}"
        if log.requests:
            line += f' for "{log.requests[-1][:90]}"'
        if log.notes:
            line += f"; note: {log.notes[-1][:120]}"
        out.append(line)
        if len(out) >= HISTORY_LINES:
            break
    return out
