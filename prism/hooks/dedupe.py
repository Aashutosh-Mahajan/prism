"""`prism hook dedupe-read`: refuse to re-read a file the agent already has, unchanged.

Opt-in (`prism init --dedupe-reads`, Claude Code `PreToolUse` on `Read`). Re-reading the same
unchanged range pays for the same lines twice and, being in context already, adds nothing. The hook
only ever **denies**, with a reason saying where the content is; it never approves a call, so it
cannot widen what the agent is allowed to do. Entries expire after 20 minutes (a compaction may have
dropped the text), a changed file is always readable, and `PRISM_DEDUPE=0` switches it off.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

EXPIRY_SECONDS = 20 * 60
DEFAULT_LIMIT = 2000  # lines a Read returns when no limit is given
MAX_FILES = 300


def _path(root: Path, session: str) -> Path:
    from prism.consent import cache_root

    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
    return cache_root(root) / "reads" / f"{digest}.json"


def _merge(ranges: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


def _covered(have: list[list[int]], lo: int, hi: int) -> bool:
    return any(a <= lo and hi <= b for a, b in _merge(have))


def _requested(tool_input: dict[str, Any]) -> tuple[int, int]:
    try:
        offset = max(1, int(tool_input.get("offset") or 1))
        limit = max(1, int(tool_input.get("limit") or DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return 1, DEFAULT_LIMIT
    return offset, offset + limit - 1


def decide(raw_stdin: str, now: float | None = None) -> str:
    """Deny confirmed repeats; remember only successfully delivered PostToolUse reads."""
    try:
        if os.environ.get("PRISM_DEDUPE") == "0":
            return ""
        from prism.consent import RepoState
        from prism.hooks.runner import _root_from, _state, parse_payload, session_of

        payload = parse_payload(raw_stdin)
        root = _root_from(payload)
        if _state(root) is not RepoState.ENABLED:
            return ""
        session = session_of(payload)
        if not session:
            return ""
        if payload.get("hook_event_name") == "SessionStart":
            # Resume/clear/compact can remove earlier tool output from context.
            _path(root, session).unlink(missing_ok=True)
            return ""
        if payload.get("tool_name") != "Read":
            return ""
        tool_input = payload.get("tool_input")
        if not session or not isinstance(tool_input, dict):
            return ""
        target = Path(str(tool_input.get("file_path") or ""))
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            return ""
        try:
            stat = target.stat()
        except OSError:
            return ""
        now = time.time() if now is None else now
        lo, hi = _requested(tool_input)
        event = payload.get("hook_event_name", "PreToolUse")
        if event not in ("PreToolUse", "PostToolUse"):
            return ""
        if event == "PostToolUse":
            covered = _delivered(payload.get("tool_response"), target)
            if covered is None:
                return ""
            lo, hi, total = covered
        path = _path(root, session)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        key = target.resolve().as_posix()
        raw = state.get(key)
        entry: dict[str, Any] | None = None
        if (
            isinstance(raw, dict)
            and raw.get("m") == stat.st_mtime_ns
            and raw.get("s") == stat.st_size
            and 0 <= now - float(raw.get("t", 0)) < EXPIRY_SECONDS
        ):
            entry = raw
        if event == "PreToolUse" and entry is not None and lo <= entry.get("total", 0):
            hi = min(hi, entry["total"])
        if event == "PreToolUse" and entry is not None and _covered(entry["cov"], lo, hi):
            try:
                shown = target.relative_to(root).as_posix()
            except ValueError:
                shown = target.as_posix()
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"PRISM: lines {lo}-{hi} of {shown} are already in your context from "
                            "an earlier read and the file has not changed since. Use that content, "
                            "or read a different range."
                        ),
                    }
                }
            )
        if event == "PreToolUse":
            return ""  # permission denial or a failed Read must leave no coverage
        coverage = entry["cov"] if entry is not None else []
        state[key] = {
            "m": stat.st_mtime_ns,
            "s": stat.st_size,
            "total": total,
            "t": entry["t"] if entry is not None else now,
            "cov": _merge([*coverage, [lo, hi]]),
        }
        if len(state) > MAX_FILES:
            for old in sorted(state, key=lambda k: state[k].get("t", 0))[: len(state) - MAX_FILES]:
                del state[old]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return ""
    except BaseException:
        return ""


def _delivered(response: Any, target: Path) -> tuple[int, int, int] | None:
    """Confirm the exact text returned, failing open for unknown/binary/truncated formats."""
    lines = target.read_text(encoding="utf-8").splitlines()
    if isinstance(response, dict) and response.get("type") == "text":
        file = response.get("file")
        if isinstance(file, dict) and isinstance(file.get("content"), str):
            start = int(file.get("startLine", 1))
            content = file["content"].splitlines()
            count = int(file.get("numLines", len(content)))
            if (
                start > 0
                and count == len(content)
                and content
                and lines[start - 1 : start - 1 + count] == content
            ):
                return start, start + count - 1, len(lines)
    if isinstance(response, str):
        numbered = re.findall(r"^\s*(\d+)[→\t](.*)$", response, re.MULTILINE)
        if numbered:
            start = int(numbered[0][0])
            if start > 0 and all(
                int(number) == start + i
                and start + i <= len(lines)
                and text == lines[start + i - 1]
                for i, (number, text) in enumerate(numbered)
            ):
                return start, start + len(numbered) - 1, len(lines)
    return None
