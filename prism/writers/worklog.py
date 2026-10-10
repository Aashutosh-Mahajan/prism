"""The work log: what each agent session asked, edited and noted, so the next one need not ask.

A new session starts with an empty context window. The index tells it how the code is built;
it does not tell it what the last session was doing: the request, which files and functions
it changed, and what it said was left. Re-deriving that costs turns of reading and of asking
the user. The hooks and tools therefore append small events to a per-session log, and the next
session-start brief carries a short summary of the most recent other session.

Events are JSON lines in `.aicontext/cache/worklog/<session digest>.jsonl` (gitignored: local
to this user, never committed). Appends are a single small write, so a hook stays fast and
concurrent writers do not corrupt each other. Logs are pruned after `RETENTION_DAYS`.
Turn it off with `worklog = false` in `[tool.prism]` or `PRISM_WORKLOG=0`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RETENTION_DAYS = 30
MAX_LOG_BYTES = 256_000  # a runaway session stops logging rather than growing without bound
MAX_TEXT = 240
MAX_ANCHOR = 120
RECENT_DAYS = 7  # the session-start summary only reaches back this far

_WORD = re.compile(r"\w{3,}")


def worklog_dir(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / "worklog"


def worklog_enabled(root: Path) -> bool:
    env = os.environ.get("PRISM_WORKLOG")
    if env is not None:
        return env != "0"
    try:
        from prism.config import load_config

        return load_config(root).extra.get("worklog", True) is not False
    except Exception:
        return True


def _digest(session: str) -> str:
    return hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def append(root: Path, session: str | None, event: dict[str, Any]) -> None:
    """Add one event to `session`'s log. Never raises: the log is an aid, not a requirement."""
    if not session:
        return
    try:
        if not worklog_enabled(root):
            return
        directory = worklog_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_digest(session)}.jsonl"
        try:
            if path.stat().st_size > MAX_LOG_BYTES:
                return
        except OSError:
            pass
        record = {"t": round(time.time(), 1), **event}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except (OSError, ValueError, TypeError):
        pass


def record_request(root: Path, session: str | None, text: str) -> None:
    if text.strip():
        append(root, session, {"type": "request", "text": _clip(text, MAX_TEXT)})


def record_delivery(
    root: Path, session: str | None, via: str, delivered: bool, why: str = ""
) -> None:
    """That a hook or a tool call answered (or deliberately stayed silent) in this session.

    `prism doctor --session` reads these to say whether PRISM was actually used."""
    append(
        root,
        session,
        {"type": "delivery", "via": via, "ok": bool(delivered), "why": _clip(why, 80)},
    )


def record_focus(root: Path, session: str | None, symbols: list[str]) -> None:
    if symbols:
        append(root, session, {"type": "focus", "symbols": symbols[:3]})


def record_edits(root: Path, session: str | None, edits: list[tuple[str, str]]) -> None:
    """`edits`: (repo-relative file, anchor line of the new text or "")."""
    for file, anchor in edits:
        event: dict[str, Any] = {"type": "edit", "file": file}
        if anchor:
            event["anchor"] = _clip(anchor, MAX_ANCHOR)
        append(root, session, event)


def record_note(root: Path, session: str | None, text: str) -> dict[str, Any]:
    """An agent's (or user's) handoff note: what changed, what is left, what to watch out for."""
    from prism.core.errors import UserError

    text = text.strip()
    if not text:
        raise UserError("a note needs some text")
    if len(text) > 600:
        raise UserError("keep notes under 600 characters: what changed, what is left")
    append(root, session or "manual", {"type": "note", "text": text})
    return {"recorded": True, "session": _digest(session or "manual")}


def prune(root: Path, now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        for entry in worklog_dir(root).glob("*.jsonl"):
            if now - entry.stat().st_mtime > RETENTION_DAYS * 86400:
                entry.unlink(missing_ok=True)
    except OSError:
        pass


# --- reading ---------------------------------------------------------------------------


@dataclass
class SessionLog:
    digest: str
    updated: float
    requests: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    edits: dict[str, list[str]] = field(default_factory=dict)  # file -> anchors
    notes: list[str] = field(default_factory=list)
    deliveries: list[tuple[str, bool, str]] = field(default_factory=list)  # (via, ok, why)

    @property
    def substantive(self) -> bool:
        return bool(self.edits or self.notes or self.focus)

    def words(self) -> set[str]:
        text = " ".join(self.requests + self.notes + self.focus + list(self.edits))
        return {w.lower() for w in _WORD.findall(text)}


def _read(path: Path) -> SessionLog | None:
    try:
        updated = path.stat().st_mtime
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    log = SessionLog(path.stem, updated)
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # a torn final line from an interrupted write
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "request" and isinstance(event.get("text"), str):
            if event["text"] not in log.requests:
                log.requests.append(event["text"])
        elif kind == "focus" and isinstance(event.get("symbols"), list):
            for sid in event["symbols"]:
                if isinstance(sid, str) and sid not in log.focus:
                    log.focus.append(sid)
        elif kind == "edit" and isinstance(event.get("file"), str):
            anchors = log.edits.setdefault(event["file"], [])
            anchor = event.get("anchor")
            if isinstance(anchor, str) and anchor and anchor not in anchors:
                anchors.append(anchor)
        elif kind == "note" and isinstance(event.get("text"), str):
            log.notes.append(event["text"])
        elif kind == "delivery" and isinstance(event.get("via"), str):
            log.deliveries.append(
                (event["via"], bool(event.get("ok")), str(event.get("why") or ""))
            )
    return log


def sessions(
    root: Path, exclude: str | None = None, days: float = RETENTION_DAYS
) -> list[SessionLog]:
    """Logged sessions, most recently active first, skipping `exclude` (a raw session id)."""
    skip = _digest(exclude) if exclude else None
    cutoff = time.time() - days * 86400
    out: list[SessionLog] = []
    try:
        paths = list(worklog_dir(root).glob("*.jsonl"))
    except OSError:
        return out
    for path in paths:
        if path.stem == skip:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        log = _read(path)
        if log is not None:
            out.append(log)
    return sorted(out, key=lambda s: (-s.updated, s.digest))
